obj-m += wire.o
wire-objs := w1.o w1_int.o w1_family.o w1_netlink.o w1_io.o
obj-m += masters/w1-gpio.o
obj-m += slaves/w1_therm.o
