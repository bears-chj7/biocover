/* Jetson Orin Nano P15 = gpiochip0 line 85. Bounded diagnostic, no pinmux writes.
 * GPIO ABI v1 is supported by this board's Linux 5.15 kernel.
 * Use open-drain value changes to avoid repeated pin configuration delays.
 * Userspace polling can still miss edges; accept only complete valid frames.
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

static int64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (int64_t)ts.tv_sec * 1000000000LL + ts.tv_nsec;
}
static int direction(int fd, unsigned flags) {
    struct gpiohandle_config cfg = {0};
    cfg.flags = flags;
    return ioctl(fd, GPIOHANDLE_SET_CONFIG_IOCTL, &cfg);
}
static void pause_ns(long ns) {
    struct timespec ts = {.tv_sec = ns / 1000000000L, .tv_nsec = ns % 1000000000L};
    while (nanosleep(&ts, &ts) && errno == EINTR) {}
}
int main(void) {
    int chip = open("/dev/gpiochip0", O_RDONLY | O_CLOEXEC);
    if (chip < 0) { perror("gpiochip0"); return 1; }
    struct gpiohandle_request req = {0};
    req.lineoffsets[0] = 85;
    req.lines = 1;
    req.flags = GPIOHANDLE_REQUEST_INPUT;
    snprintf(req.consumer_label, sizeof(req.consumer_label), "biocover-dht22");
    if (ioctl(chip, GPIO_GET_LINEHANDLE_IOCTL, &req)) {
        perror("P15 request"); close(chip); return 1;
    }
    int valid = 0, error = 0;
    struct gpiohandle_config od = {0};
    od.flags = GPIOHANDLE_REQUEST_OUTPUT | GPIOHANDLE_REQUEST_OPEN_DRAIN;
    od.default_values[0] = 1;
    if (ioctl(req.fd, GPIOHANDLE_SET_CONFIG_IOCTL, &od)) {
        perror("P15 open drain"); close(req.fd); close(chip); return 1;
    }
    for (int attempt = 0; attempt < 8; attempt++) {
        struct gpiohandle_data drive = {0};
        if (ioctl(req.fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &drive)) {
            perror("P15 start low"); error = 1; break;
        }
        pause_ns(2000000);
        drive.values[0] = 1; /* Open drain: release, never push high. */
        if (ioctl(req.fd, GPIOHANDLE_SET_LINE_VALUES_IOCTL, &drive)) {
            perror("P15 release"); error = 1; break;
        }
        struct gpiohandle_data data = {0};
        int last = -1, count = 0;
        int64_t rise = 0, start = now_ns();
        double highs[96];
        while (now_ns() - start < 8000000) {
            if (ioctl(req.fd, GPIOHANDLE_GET_LINE_VALUES_IOCTL, &data)) {
                perror("P15 read"); error = 1; break;
            }
            int v = data.values[0];
            int64_t t = now_ns();
            if (last == 0 && v == 1) rise = t;
            if (last == 1 && v == 0 && rise && count < 96) {
                highs[count++] = (t - rise) / 1000.0;
                rise = 0;
            }
            last = v;
        }
        int good = !error && count == 41 && highs[0] >= 55 && highs[0] <= 115;
        unsigned b[5] = {0};
        if (good) {
            for (int i = 0; i < 40; i++) {
                double us = highs[i+1];
                if (us < 10 || us > 100) good = 0;
                b[i/8] = (b[i/8] << 1) | (us > 50);
            }
            good = good && (((b[0]+b[1]+b[2]+b[3]) & 255) == b[4]);
        }
        double humidity = (b[0]*256+b[1])/10.0;
        double temperature = ((b[2]&127)*256+b[3])/10.0 * ((b[2]&128) ? -1 : 1);
        good = good && humidity >= 0 && humidity <= 100 && temperature >= -40 && temperature <= 80;
        printf("{\"attempt\":%d,\"high_pulse_count\":%d,\"valid_frame\":%s", attempt+1,count,good?"true":"false");
        if (good) {
            valid++;
            printf(",\"humidity_pct\":%.1f,\"temperature_C\":%.1f,\"bytes\":[%u,%u,%u,%u,%u]",humidity,temperature,b[0],b[1],b[2],b[3],b[4]);
        }
        printf(",\"high_pulses_us\":[");
        for (int i=0;i<count;i++) printf("%s%.1f",i?",":"",highs[i]);
        puts("]}"); fflush(stdout);
        if (error) break;
        if (attempt < 7) pause_ns(2100000000L);
    }
    if (direction(req.fd, GPIOHANDLE_REQUEST_INPUT)) { perror("restore input"); error = 1; }
    close(req.fd); close(chip);
    return error ? 1 : (valid ? 0 : 2);
}
