obj-m += tcp_prague.o
obj-m += sch_dualpi2.o

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules
	
clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

unload:
	-./test_bottleneck.sh -c
	-sudo rmmod tcp_prague.ko
	-sudo rmmod sch_dualpi2.ko

load: unload
	sudo insmod tcp_prague.ko
	sudo insmod sch_dualpi2.ko
