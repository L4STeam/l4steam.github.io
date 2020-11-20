CFLAGS+=$(shell pcap-config --cflags)
LDLIBS+=$(shell pcap-config --libs)

EXE=qdelay_dump

$(EXE): $(EXE).o

clean:
	rm -f $(EXE) *.o
