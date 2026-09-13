/* DS18B20 P7 presence-only diagnostic for Orin Nano.
 * Requires w1-gpio temporarily unbound by check_ds18_presence.py.
 * GPIO base 0x02210000 + AC bank0/port1 offset0x200 + pin6*0x20.
 * Only P7 control registers are changed; saved input state is restored.
 * Sends RESET only, no ROM/EEPROM writes, conversion, or pinmux changes.
 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

static volatile sig_atomic_t stop;
static void interrupted(int sig) {(void)sig;stop=1;}
static int64_t ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (int64_t)t.tv_sec*1000000000LL+t.tv_nsec;}
static void pause_ns(long n){struct timespec t={n/1000000000L,n%1000000000L};while(!stop&&nanosleep(&t,&t)&&errno==EINTR){}}
static void put(volatile uint32_t *r,uint32_t v){*r=v;__asm__ volatile("dsb sy" ::: "memory");}
static int board_ok(void){
    char b[512]={0};int f=open("/proc/device-tree/compatible",O_RDONLY);
    if(f<0)return 0;
    ssize_t n=read(f,b,sizeof(b)-1);close(f);
    if(n<=0)return 0;
    for(ssize_t i=0;i<n;i++)if(!b[i])b[i]=' ';
    return strstr(b,"nvidia,p3768-0000+p3767-0005")!=NULL;
}
int main(void){
    if(!board_ok()){fputs("Unsupported board; refusing MMIO.\n",stderr);return 1;}
    struct sigaction sa={0};sa.sa_handler=interrupted;sigemptyset(&sa.sa_mask);
    sigaction(SIGINT,&sa,NULL);sigaction(SIGTERM,&sa,NULL);
    int chip=open("/dev/gpiochip0",O_RDONLY|O_CLOEXEC);
    if(chip<0){perror("gpiochip0");return 1;}
    struct gpiochip_info ci={0};struct gpioline_info li={0};li.line_offset=144;
    if(ioctl(chip,GPIO_GET_CHIPINFO_IOCTL,&ci)||ioctl(chip,GPIO_GET_LINEINFO_IOCTL,&li)||
       strcmp(ci.label,"tegra234-gpio")||strcmp(li.name,"PAC.06")){
        fputs("GPIO identity mismatch.\n",stderr);close(chip);return 1;
    }
    struct gpiohandle_request req={0};req.lineoffsets[0]=144;req.lines=1;req.flags=GPIOHANDLE_REQUEST_INPUT;
    snprintf(req.consumer_label,sizeof(req.consumer_label),"biocover-ds-presence");
    if(ioctl(chip,GPIO_GET_LINEHANDLE_IOCTL,&req)){perror("P7 busy/request");close(chip);return 1;}
    int mem=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);
    if(mem<0){perror("/dev/mem");close(req.fd);close(chip);return 1;}
    long page=sysconf(_SC_PAGESIZE);const off_t addr=0x022102c0;
    off_t base=addr & ~((off_t)page-1);
    void *map=mmap(NULL,(size_t)page,PROT_READ|PROT_WRITE,MAP_SHARED,mem,base);
    if(map==MAP_FAILED){perror("mmap");close(mem);close(req.fd);close(chip);return 1;}
    volatile uint32_t *reg=(volatile uint32_t *)((char *)map+(addr-base));
    uint32_t cfg=reg[0],ctl=reg[3],value=reg[4];
    /* Reject output, debounce or enabled IRQ. Dormant trigger-type/level bits
     * may remain after a previous edge request and are not active IRQs. */
    if(!(cfg&1)||(cfg&0x62)||!(ctl&1)){
        fprintf(stderr,"Unexpected P7 config: 0x%x ctl=0x%x; no MMIO writes.\n",cfg,ctl);
        munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);return 1;
    }
    pause_ns(100000000L);
    struct gpiohandle_data sample={0};
    if(ioctl(req.fd,GPIOHANDLE_GET_LINE_VALUES_IOCTL,&sample)||sample.values[0]!=(reg[2]&1)){
        fputs("GPIO/MMIO input mismatch; no MMIO writes.\n",stderr);
        munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);return 1;
    }
    printf("{\"pin\":7,\"address\":\"0x022102c0\",\"idle\":%u}\n",reg[2]&1);fflush(stdout);
    uint32_t polling_cfg=cfg&~0x7eU;
    int valid=0,error=0;
    for(int attempt=1;attempt<=3&&!stop;attempt++){
        if(!(reg[2]&1)){fputs("P7 idle LOW; no reset sent.\n",stderr);error=1;break;}
        put(&reg[4],value&~1U);put(&reg[0],polling_cfg|3U);put(&reg[3],ctl&~1U);
        int64_t begin=ns();while(!stop&&ns()-begin<500000){}
        unsigned driven_low=!(reg[2]&1);
        put(&reg[3],ctl|1U);put(&reg[0],polling_cfg);
        int64_t released=ns();int levels[32]={0};int64_t times[32]={0};
        int n=1;levels[0]=reg[2]&1;times[0]=released;
        while(!stop&&ns()-released<1000000&&n<32){
            int v=reg[2]&1;
            if(v!=levels[n-1]){times[n]=ns();levels[n]=v;n++;}
        }
        int present=0;
        /* Require HIGH after release, then delayed LOW, then return HIGH. */
        for(int i=1;i<n-1;i++){
            double delay=(times[i]-released)/1000.0;
            double width=(times[i+1]-times[i])/1000.0;
            if(levels[i-1]==1&&levels[i]==0&&levels[i+1]==1&&delay>=10&&delay<=100&&width>=40&&width<=300)present=1;
        }
        present=present&&driven_low&&!stop;
        valid+=present;
        printf("{\"attempt\":%d,\"driven_low\":%s,\"presence_candidate\":%s,\"transitions\":[",attempt,driven_low?"true":"false",present?"true":"false");
        for(int i=0;i<n;i++)printf("%s{\"us\":%.1f,\"level\":%d}",i?",":"",(times[i]-released)/1000.0,levels[i]);
        puts("]}");fflush(stdout);
        if(!driven_low){error=1;break;}
        if(attempt<3)pause_ns(500000000L);
    }
    /* Restore the input state acquired from gpiolib before releasing ownership. */
    put(&reg[3],ctl|1U);put(&reg[0],cfg);put(&reg[4],value);put(&reg[3],ctl);
    munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);
    return error?1:(stop?130:(valid?0:2));
}
