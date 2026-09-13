/* Orin Nano Super P15-only timing diagnostic. Requires root /dev/mem access.
 * GPIO line ownership is acquired first; only PN.01's three control registers
 * are written and restored. No pinmux, SPI or P7 registers are changed.
 * Register layout/port mapping: Linux drivers/gpio/gpio-tegra186.c.
 * DT gpio base 0x02210000 + bank N=2 *0x1000 + port=1 *0x200 + pin1 *0x20.
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
    struct gpiochip_info ci={0};struct gpioline_info li={0};li.line_offset=85;
    if(ioctl(chip,GPIO_GET_CHIPINFO_IOCTL,&ci)||ioctl(chip,GPIO_GET_LINEINFO_IOCTL,&li)||
       strcmp(ci.label,"tegra234-gpio")||strcmp(li.name,"PN.01")){
        fputs("GPIO identity mismatch.\n",stderr);close(chip);return 1;
    }
    struct gpiohandle_request req={0};req.lineoffsets[0]=85;req.lines=1;req.flags=GPIOHANDLE_REQUEST_INPUT;
    snprintf(req.consumer_label,sizeof(req.consumer_label),"biocover-dht-mmio");
    if(ioctl(chip,GPIO_GET_LINEHANDLE_IOCTL,&req)){perror("P15 busy/request");close(chip);return 1;}
    int mem=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);
    if(mem<0){perror("/dev/mem");close(req.fd);close(chip);return 1;}
    long page=sysconf(_SC_PAGESIZE);const off_t addr=0x02212220;
    off_t base=addr & ~((off_t)page-1);
    void *map=mmap(NULL,(size_t)page,PROT_READ|PROT_WRITE,MAP_SHARED,mem,base);
    if(map==MAP_FAILED){perror("mmap");close(mem);close(req.fd);close(chip);return 1;}
    volatile uint32_t *reg=(volatile uint32_t *)((char *)map+(addr-base));
    uint32_t cfg=reg[0],ctl=reg[3],value=reg[4];
    /* Acquired input must be floated, enabled and not interrupt-driven. */
    if(!(cfg&1)||(cfg&0x7e)||!(ctl&1)){
        fprintf(stderr,"Unexpected P15 config: 0x%x ctl=0x%x; no MMIO writes.\n",cfg,ctl);
        munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);return 1;
    }
    struct gpiohandle_data sample={0};
    if(ioctl(req.fd,GPIOHANDLE_GET_LINE_VALUES_IOCTL,&sample)||sample.values[0]!=(reg[2]&1)){
        fputs("GPIO/MMIO input mismatch; no MMIO writes.\n",stderr);
        munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);return 1;
    }
    printf("{\"pin\":15,\"address\":\"0x02212220\",\"config\":%u,\"idle\":%u}\n",cfg,reg[2]&1);fflush(stdout);
    int valid=0,error=0;
    for(int attempt=1;attempt<=5&&!stop;attempt++){
        int levels[100]={0};int64_t times[100]={0};double highs[50]={0};
        if(!(reg[2]&1)){fprintf(stderr,"P15 idle LOW; stop before request.\n");error=1;break;}
        /* Drive only LOW, then float before changing direction to input. */
        put(&reg[4],value&~1U);put(&reg[0],cfg|3U);put(&reg[3],ctl&~1U);
        int64_t low_start=ns();while(!stop&&ns()-low_start<1100000){}
        unsigned low_level=reg[2]&1;
        put(&reg[3],ctl|1U);put(&reg[0],cfg&~2U);
        int64_t begin=ns();int count=1;levels[0]=reg[2]&1;times[0]=begin;
        while(!stop&&ns()-begin<7000000&&count<100){
            int v=reg[2]&1;
            if(v!=levels[count-1]){times[count]=ns();levels[count]=v;count++;}
        }
        int hc=0;
        for(int i=0;i<count-1;i++)if(levels[i]==1&&levels[i+1]==0&&hc<50)highs[hc++]=(times[i+1]-times[i])/1000.0;
        int start=hc-40;
        int good=!stop&&low_level==0&&(hc==41||hc==42)&&highs[start-1]>=55&&highs[start-1]<=115;
        unsigned b[5]={0};
        if(good){
            for(int i=0;i<40;i++){
                double width=highs[start+i];
                if(width<10||width>100||(width>40&&width<55))good=0;
                b[i/8]=(b[i/8]<<1)|(width>=55);
            }
            good=good&&(((b[0]+b[1]+b[2]+b[3])&255)==b[4])&&(b[0]|b[1]|b[2]|b[3]);
        }
        double h=(b[0]*256+b[1])/10.0,t=((b[2]&127)*256+b[3])/10.0*((b[2]&128)?-1:1);
        good=good&&h<=100&&t>=-40&&t<=80;
        printf("{\"attempt\":%d,\"low_level\":%u,\"edges\":%d,\"high_count\":%d,\"valid\":%s",attempt,low_level,count-1,hc,good?"true":"false");
        if(good){valid++;printf(",\"temperature_C\":%.1f,\"humidity_pct\":%.1f,\"bytes\":[%u,%u,%u,%u,%u]",t,h,b[0],b[1],b[2],b[3],b[4]);}
        printf(",\"high_us\":[");for(int i=0;i<hc;i++)printf("%s%.1f",i?",":"",highs[i]);puts("]}");fflush(stdout);
        if(low_level){error=1;break;}
        if(attempt<5)pause_ns(2100000000L);
    }
    /* Restore the input state acquired from gpiolib before releasing ownership. */
    put(&reg[3],ctl|1U);put(&reg[0],cfg);put(&reg[4],value);put(&reg[3],ctl);
    munmap(map,(size_t)page);close(mem);close(req.fd);close(chip);
    return error?1:(stop?130:(valid?0:2));
}
