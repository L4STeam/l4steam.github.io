obj-m += sch_dualpi2.o
obj-m += sch_fq_codel_tst.o

all:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules
	
clean:
	$(MAKE) -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

unload:
	-sudo rmmod sch_dualpi2
	-sudo rmmod sch_fq_codel_tst

load: unload
	sudo insmod sch_dualpi2.ko
	sudo insmod sch_fq_codel_tst.ko
