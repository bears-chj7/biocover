import os,fcntl,ctypes as C,struct,time,json

def adc():
 fd=os.open('/dev/spidev0.0',os.O_RDWR); old=bytearray(1); fcntl.ioctl(fd,0x80016b01,old,True)
 try:
  fcntl.ioctl(fd,0x40016b01,bytes([0])); out={}
  for speed in [100000,500000]:
   values=[[] for _ in range(5)]; frames=[]
   for i in range(10):
    row=[]
    for ch in range(5):
     tx=(C.c_ubyte*3)(1,(8+ch)<<4,0); rx=(C.c_ubyte*3)()
     msg=struct.pack('=QQIIHBBBBBB',C.addressof(tx),C.addressof(rx),3,speed,0,8,0,0,0,0,0)
     fcntl.ioctl(fd,0x40206b00,msg); values[ch].append(((rx[1]&3)<<8)|rx[2]); row.append(bytes(rx).hex())
    frames.append(row); time.sleep(.2)
   out[speed]={'raw':values,'frames':frames}
  return out
 finally:
  fcntl.ioctl(fd,0x40016b01,old); os.close(fd)

def dht():
 lib=C.CDLL('libgpiod.so.2',use_errno=True)
 for name,ret,args in [('gpiod_chip_open',C.c_void_p,[C.c_char_p]),('gpiod_chip_get_line',C.c_void_p,[C.c_void_p,C.c_uint]),('gpiod_line_request_output',C.c_int,[C.c_void_p,C.c_char_p,C.c_int]),('gpiod_line_request_input',C.c_int,[C.c_void_p,C.c_char_p]),('gpiod_line_get_value',C.c_int,[C.c_void_p]),('gpiod_line_release',None,[C.c_void_p]),('gpiod_chip_close',None,[C.c_void_p])]:
  fn=getattr(lib,name); fn.restype=ret; fn.argtypes=args
 chip=lib.gpiod_chip_open(b'/dev/gpiochip0')
 if not chip: raise OSError(C.get_errno(),'gpio chip open')
 line=lib.gpiod_chip_get_line(chip,85); out=[]
 try:
  for _ in range(3):
   if lib.gpiod_line_request_output(line,b'sensor-check',0)<0: raise OSError(C.get_errno(),'DHT request low')
   time.sleep(.002); lib.gpiod_line_release(line)
   if lib.gpiod_line_request_input(line,b'sensor-check')<0: raise OSError(C.get_errno(),'DHT request input')
   edges=[]; clock=time.perf_counter_ns; begin=clock(); last=lib.gpiod_line_get_value(line); initial=last
   while clock()-begin<10_000_000:
    value=lib.gpiod_line_get_value(line)
    if value!=last: edges.append((clock()-begin,value)); last=value
   lib.gpiod_line_release(line)
   highs=[(edges[i+1][0]-t)/1000 for i,(t,v) in enumerate(edges[:-1]) if v==1 and edges[i+1][1]==0]
   item={'initial_level':initial,'edges':len(edges),'high_pulses_us':[round(x,1) for x in highs]}
   if len(highs)>=40:
    bits=[int(x>50) for x in highs[-40:]]; data=[sum(bits[j*8+k]<<(7-k) for k in range(8)) for j in range(5)]
    item['bytes']=data; item['checksum_ok']=sum(data[:4])%256==data[4]
    if item['checksum_ok']: item['humidity_pct']=(data[0]*256+data[1])/10; item['temperature_C']=((data[2]&127)*256+data[3])/10*(-1 if data[2]&128 else 1)
   out.append(item); time.sleep(2.1)
  return out
 finally: lib.gpiod_chip_close(chip)

if __name__ == '__main__':
 for name,fn in [('MCP3008',adc),('DHT22',dht)]:
  try: print(json.dumps({name:fn()}),flush=True)
  except Exception as e: print(json.dumps({name:{'error':str(e)}}),flush=True)
