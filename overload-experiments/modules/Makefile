obj-m += sch_dualpi2.o

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules
	
clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

unload:
	-sudo rmmod sch_dualpi2

load: unload
	sudo insmod sch_dualpi2.ko
