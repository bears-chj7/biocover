/* Jetson Orin Nano P15 (gpiochip0 offset 85), GPIO v2 edge timestamps.
 * Diagnostic only: pinmux unchanged, no P7 access, restore input on exit.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
static int64_t ns(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
    return (int64_t)t.tv_sec*1000000000LL+t.tv_nsec;
}
static void pause_ns(long n) {
    struct timespec t={n/1000000000L,n%1000000000L};
    while(nanosleep(&t,&t) && errno==EINTR) {}
}
static int config(int fd,uint64_t flags) {
    struct gpio_v2_line_config c={0}; c.flags=flags;
    return ioctl(fd,GPIO_V2_LINE_SET_CONFIG_IOCTL,&c);
}
int main(void) {
    int chip=open("/dev/gpiochip0",O_RDONLY|O_CLOEXEC);
    if(chip<0){perror("chip");return 1;}
    struct gpio_v2_line_request req={0};
    req.offsets[0]=85;req.num_lines=1;req.event_buffer_size=128;
    req.config.flags=GPIO_V2_LINE_FLAG_INPUT;
    snprintf(req.consumer,sizeof(req.consumer),"biocover-dht-events");
    if(ioctl(chip,GPIO_V2_GET_LINE_IOCTL,&req)){perror("request");close(chip);return 1;}
    int valid=0,error=0;
    if(fcntl(req.fd,F_SETFL,O_NONBLOCK)<0){perror("nonblocking");close(req.fd);close(chip);return 1;}
    for(int attempt=1;attempt<=5;attempt++) {
        struct gpio_v2_line_event events[128],e;
        int n=0;
        while(read(req.fd,&e,sizeof(e))==(ssize_t)sizeof(e)) {}
        if(config(req.fd,GPIO_V2_LINE_FLAG_OUTPUT)){perror("low");error=1;break;}
        pause_ns(2000000);
        int64_t begin=ns();
        if(config(req.fd,GPIO_V2_LINE_FLAG_INPUT|GPIO_V2_LINE_FLAG_EDGE_RISING|GPIO_V2_LINE_FLAG_EDGE_FALLING)){
            perror("edges");error=1;break;
        }
        int64_t returned=ns();
        while(ns()-returned<20000000) {
            struct pollfd p={req.fd,POLLIN,0};
            int pr=poll(&p,1,2);
            if(pr<0 && errno!=EINTR){perror("poll");error=1;break;}
            if(pr>0 && (p.revents&(POLLERR|POLLNVAL))){error=1;break;}
            while(n<128) {
                ssize_t bytes=read(req.fd,&events[n],sizeof(events[n]));
                if(bytes==(ssize_t)sizeof(events[n])) n++;
                else if(bytes<0 && (errno==EAGAIN||errno==EINTR)) break;
                else {error=1;break;}
            }
            if(error||n==128)break;
        }
        double highs[64];int count=0,gaps=0;uint64_t rise=0;
        for(int i=0;i<n;i++) {
            if(i && events[i].seqno!=events[i-1].seqno+1)gaps++;
            if(events[i].id==GPIO_V2_LINE_EVENT_RISING_EDGE)rise=events[i].timestamp_ns;
            else if(rise && count<64){highs[count++]=(events[i].timestamp_ns-rise)/1000.0;rise=0;}
        }
        int good=!error&&!gaps&&count==41&&highs[0]>55&&highs[0]<115;
        unsigned b[5]={0};
        if(good) {
            for(int i=0;i<40;i++){
                if(highs[i+1]<10||highs[i+1]>100)good=0;
                b[i/8]=(b[i/8]<<1)|(highs[i+1]>50);
            }
            good=good&&(((b[0]+b[1]+b[2]+b[3])&255)==b[4]);
        }
        double h=(b[0]*256+b[1])/10.0,t=((b[2]&127)*256+b[3])/10.0*((b[2]&128)?-1:1);
        good=good&&h<=100&&t>=-40&&t<=80;
        printf("{\"attempt\":%d,\"config_us\":%.1f,\"event_count\":%d,\"sequence_gaps\":%d,\"valid\":%s",attempt,(returned-begin)/1000.0,n,gaps,good?"true":"false");
        if(good){valid++;printf(",\"temperature_C\":%.1f,\"humidity_pct\":%.1f",t,h);}
        printf(",\"high_us\":[");for(int i=0;i<count;i++)printf("%s%.1f",i?",":"",highs[i]);puts("]}");fflush(stdout);
        if(error)break;
        if(attempt<5)pause_ns(2100000000L);
    }
    if(config(req.fd,GPIO_V2_LINE_FLAG_INPUT)){perror("restore");error=1;}
    close(req.fd);close(chip);return error?1:(valid?0:2);
}
