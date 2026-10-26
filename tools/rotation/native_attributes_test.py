#!/usr/bin/env python3
"""Exercise production attribute ownership, transform publication and display isolation."""
from test_support import FB, method, run

methods = '\n'.join(method(FB, name) for name in [
    'bool NVRMNVDAFramebuffer::setProperty(', 'void NVRMNVDAFramebuffer::publishRotatedSizes('])
fixture = r'''
#include <IOKit/graphics/IOGraphicsTypes.h>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <vector>
#include <initializer_list>
using NvU32=uint32_t;using IOLock=std::mutex;
static const char *gIOServicePlane="IOService";
static bool failData=false;
#define FBLOG(...) ((void)0)
static UInt32 OSSwapHostToBigInt32(UInt32 v){return __builtin_bswap32(v);}
static int OSAddAtomic(int,volatile int *p){return *p;}
struct OSObject{int refs=1;virtual ~OSObject(){};void retain(){++refs;}void release(){assert(refs>0);if(!--refs)delete this;}};
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
#define OSSafeReleaseNULL(p) do{if(p){p->release();p=nullptr;}}while(0)
struct OSSymbol{std::string key;bool isEqualTo(const char *s)const{return key==s;}};
struct OSNumber:OSObject{UInt32 value;explicit OSNumber(UInt32 v):value(v){};UInt32 unsigned32BitValue(){return value;}};
struct OSData:OSObject{std::vector<unsigned char> bytes;
 static OSData *withBytes(const void *p,size_t n){if(failData)return nullptr;auto *d=new OSData;d->bytes.assign((const unsigned char *)p,(const unsigned char *)p+n);return d;}};
struct OSArray:OSObject{std::vector<OSObject *> values;
 static OSArray *withCapacity(unsigned){return new OSArray;}
 bool setObject(OSObject *p){p->retain();values.push_back(p);return true;}unsigned getCount(){return values.size();}
 ~OSArray(){for(auto *p:values)p->release();}};
struct OSDictionary:OSObject{std::map<std::string,OSObject *> values;
 static OSDictionary *withDictionary(OSDictionary *old){auto *d=new OSDictionary;for(auto &v:old->values)d->setObject(v.first.c_str(),v.second);return d;}
 OSObject *getObject(const char *k){auto i=values.find(k);return i==values.end()?nullptr:i->second;}
 bool setObject(const char *k,OSObject *v){v->retain();removeObject(k);values[k]=v;return true;}
 void removeObject(const char *k){auto i=values.find(k);if(i!=values.end()){i->second->release();values.erase(i);}}
 ~OSDictionary(){for(auto &v:values)v.second->release();}};
struct OSIterator:OSObject{OSObject *child;bool seen=false;explicit OSIterator(OSObject *p):child(p){if(child)child->retain();}
 OSObject *getNextObject(){if(seen)return nullptr;seen=true;return child;}~OSIterator(){if(child)child->release();}};
struct IORegistryEntry:OSObject{
 OSDictionary *properties=new OSDictionary;IORegistryEntry *child=nullptr;bool connect=false,accepted=true;
 OSIterator *getChildIterator(const char *){return new OSIterator(child);}
 void *metaCast(const char *s){return connect&&!strcmp(s,"IODisplayConnect")?this:nullptr;}
 IORegistryEntry *copyChildEntry(const char *){if(child)child->retain();return child;}
 OSObject *copyProperty(const char *s){OSObject *v=properties->getObject(s);if(v)v->retain();return v;}
 bool setProperty(const char *s,OSObject *v){return accepted&&properties->setObject(s,v);}
 bool setProperty(const OSSymbol *s,OSObject *v){return setProperty(s->key.c_str(),v);}
 ~IORegistryEntry(){properties->release();if(child)child->release();}
};
using IOFramebuffer=IORegistryEntry;
struct NVRMCallReference{OSObject *owner;explicit NVRMCallReference(OSObject *p):owner(p){}~NVRMCallReference(){owner->release();}};
struct NVRMRotationAttributesGuard{IOLock *lock;explicit NVRMRotationAttributesGuard(IOLock *l):lock(l){if(lock)lock->lock();}
 ~NVRMRotationAttributesGuard(){if(lock)lock->unlock();}bool valid(){return lock;}};
struct NVRMNVDAFramebuffer:IOFramebuffer{
 using IOFramebuffer::setProperty;
 bool fRotationEnabled=true;volatile int fStopping=0;UInt32 fTransform=0;unsigned fNDT=10,fIndex=0;
 unsigned fBootW=1920,fBootH=1080,fRasterW=1920,fRasterH=1080;
 IOLock mutex,*fRotationAttributesLock=&mutex;OSArray *fRotationPublishedSizes=nullptr;
 bool setProperty(const OSSymbol *,OSObject *);void publishRotatedSizes(bool force=true);
 ~NVRMNVDAFramebuffer(){if(fRotationPublishedSizes)fRotationPublishedSizes->release();}
 IORegistryEntry *setup(){child=new IORegistryEntry;child->connect=true;auto *display=child->child=new IORegistryEntry;
 auto *attrs=new OSDictionary;display->setProperty("IODisplayAttributes",attrs);attrs->release();return display;}
};
@@METHODS@@
static OSDictionary *attrs(IORegistryEntry *d){return OSDynamicCast(OSDictionary,d->properties->getObject("IODisplayAttributes"));}
static void turn(NVRMNVDAFramebuffer &fb,unsigned value){OSSymbol key{"IOFBTransform"};auto *v=new OSNumber(value);assert(fb.setProperty(&key,v));v->release();}
int main(){
 NVRMNVDAFramebuffer first,second;auto *d1=first.setup(),*d2=second.setup();
 auto *setting=new OSNumber(42);attrs(d1)->setObject("other-setting",setting);setting->release();
 turn(first,0x30);assert(first.fTransform==0x30&&first.fNDT==0);
 assert(first.fRotationPublishedSizes&&attrs(d1)->getObject("scale-resolutions")==first.fRotationPublishedSizes);
 assert(first.fRotationPublishedSizes->getCount()==1&&!second.fRotationPublishedSizes&&!attrs(d2)->getObject("scale-resolutions"));
 auto *entry=OSDynamicCast(OSData,first.fRotationPublishedSizes->values[0]);assert(entry&&entry->bytes.size()==20);
 UInt32 words[5];memcpy(words,entry->bytes.data(),sizeof words);
 assert(words[0]==__builtin_bswap32(1920u)&&words[1]==__builtin_bswap32(1080u));
 assert(words[4]==__builtin_bswap32((UInt32)kDisplayModeValidForMirroringFlag));
 first.fRasterW=2560;first.fRasterH=1440;first.publishRotatedSizes();assert(first.fRotationPublishedSizes->getCount()==2);
 turn(first,0);assert(!first.fRotationPublishedSizes&&!attrs(d1)->getObject("scale-resolutions"));
 assert(attrs(d1)->getObject("other-setting"));
 // A pre-existing user override survives both entering rotation and restoring Standard.
 auto *user=OSArray::withCapacity(1);auto *token=new OSNumber(7);user->setObject(token);token->release();
 attrs(d2)->setObject("scale-resolutions",user);
 turn(second,0x50);assert(attrs(d2)->getObject("scale-resolutions")==user&&!second.fRotationPublishedSizes);
 turn(second,0);assert(attrs(d2)->getObject("scale-resolutions")==user);
 // External replacement of our own list also becomes the external owner's property.
 turn(first,0x30);attrs(d1)->setObject("scale-resolutions",user);
 turn(first,0);assert(attrs(d1)->getObject("scale-resolutions")==user);
 user->release();
 // Allocation refusal or a rejected property update cannot publish partial geometry.
 NVRMNVDAFramebuffer failed;auto *df=failed.setup();failed.fTransform=0x30;failData=true;
 failed.publishRotatedSizes();assert(!failed.fRotationPublishedSizes&&!attrs(df)->getObject("scale-resolutions"));failData=false;
 failed.accepted=false;OSSymbol key{"IOFBTransform"};auto *number=new OSNumber(0x50);
 assert(!failed.setProperty(&key,number)&&failed.fTransform==0x30);number->release();
 failed.fRotationEnabled=false;failed.publishRotatedSizes();assert(!failed.fRotationPublishedSizes);
 puts("PASS: production per-display scale attributes and transform publication; 20-byte native modes, existing/externally replaced overrides, rejection/allocation failures, balanced references and independent heads");
}
'''
run(fixture.replace('@@METHODS@@', methods))
