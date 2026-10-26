#!/usr/bin/env python3
"""Exercise production display naming and the controller's path round-trip check."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
fb = (root / 'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()
control = (root / 'tools/rotation/control.mm').read_text()


def method(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


identity = method(fb, 'void NVRMNVDAFramebuffer::configureDisplayIdentity(')
lookup = method(control, 'static bool framebufferPathMatches(')
start = method(fb, 'bool NVRMNVDAFramebuffer::start(')
assert start.index('fIndex = ') < start.index('configureDisplayIdentity(provider);')
assert start.index('configureDisplayIdentity(provider);') < start.index('super::start(provider)')
# Refuse an ambiguous selected path before either the restore timer or setter runs.
main = method(control, 'int main(')
guard = main.index('if (!framebufferPathMatches(')
assert guard < main.index('posix_spawn(&watchdog') < main.index('IOServiceRequestProbe(fb, kNVRMSetTransform | bits')

fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
static const char *gIOServicePlane="IOService",*kIOServicePlane=gIOServicePlane;
enum {kIOMainPortDefault=0,KERN_SUCCESS=0};
struct IOService {
    IOService *parent=nullptr;std::string name,location;uint64_t id;
    int references=0,locationChanges=0;bool pathFails=false;
    IOService(IOService *p,const char *n,uint64_t i):parent(p),name(n),id(i){}
    void setLocation(const char *value,const char *plane){
        assert(plane==gIOServicePlane);location=value;++locationChanges;
    }
    std::string component()const{return name+(location.empty()?"":"@"+location);}
    std::string path()const{return parent?parent->path()+"/"+component():"IOService:/"+component();}
};
using io_service_t=IOService *;using io_registry_entry_t=IOService *;
using io_string_t=char[512];
static std::vector<IOService *> registry;
static uint64_t entryID(IOService *entry){return entry->id;}
static int IORegistryEntryGetPath(IOService *entry,const char *plane,char *path){
    assert(plane==kIOServicePlane);
    if(entry->pathFails)return -1;
    assert(entry->path().size()<512);strcpy(path,entry->path().c_str());return 0;
}
static IOService *IORegistryEntryFromPath(int port,const char *path){
    assert(port==kIOMainPortDefault);
    for(IOService *entry:registry)if(entry->path()==path){++entry->references;return entry;}
    return nullptr;
}
static void IOObjectRelease(IOService *entry){assert(entry->references>0);--entry->references;}
struct NVRMNVDAFramebuffer {
    unsigned fIndex;void configureDisplayIdentity(IOService *);
};
@@IDENTITY@@
@@LOOKUP@@
int main(){
    IOService gpu(nullptr,"GPU@0",1),otherGPU(nullptr,"GPU@1",2);
    std::vector<IOService *> nubs,outputs;
    for(IOService *provider:{&gpu,&otherGPU})for(unsigned head=0;head<4;++head){
        auto *nub=new IOService(provider,"NVRMDisplay",10+registry.size());
        auto *output=new IOService(nub,"NVRMFramebuffer",100+registry.size());
        nubs.push_back(nub);outputs.push_back(output);registry.push_back(output);
    }
    // The actual report: distinct registry IDs/indices, identical paths. A
    // successful lookup of that path is insufficient to identify a monitor.
    io_string_t path;uint64_t resolved=0;
    assert(framebufferPathMatches(outputs[0],path,&resolved));
    for(unsigned head=1;head<4;++head){
        assert(outputs[head]->id!=outputs[0]->id);
        assert(outputs[head]->path()==outputs[0]->path());
        assert(!framebufferPathMatches(outputs[head],path,&resolved));
        assert(resolved==outputs[0]->id);
    }
    for(unsigned i=0;i<nubs.size();++i){
        NVRMNVDAFramebuffer fb{i%4};fb.configureDisplayIdentity(nubs[i]);
        assert(fb.fIndex==i%4&&nubs[i]->name=="NVRMDisplay");
        assert(nubs[i]->location==std::to_string(i%4));
    }
    for(unsigned i=0;i<outputs.size();++i){
        assert(framebufferPathMatches(outputs[i],path,&resolved));
        assert(resolved==outputs[i]->id);
        for(unsigned j=0;j<i;++j)assert(outputs[i]->path()!=outputs[j]->path());
        assert(outputs[i]->references==0);
    }
    // Reusing a display nub does not change its identity or move another head.
    const auto saved=outputs[2]->path();
    NVRMNVDAFramebuffer secondary{2};secondary.configureDisplayIdentity(nubs[2]);
    assert(outputs[2]->path()==saved&&framebufferPathMatches(outputs[2],path,&resolved));
    outputs[2]->pathFails=true;assert(!framebufferPathMatches(outputs[2],path,&resolved)&&!resolved&&!path[0]);
    outputs[2]->pathFails=false;
    IOService missing(&gpu,"missing",999);
    assert(!framebufferPathMatches(&missing,path,&resolved)&&!resolved);
    for(IOService *entry:outputs){assert(!entry->references);delete entry;}
    for(IOService *entry:nubs)delete entry;
    puts("PASS: reproduced four-head path collision; production naming gives unique paths on two GPUs; selected-head round trips, unchanged indices, reused nubs, lookup failure and balanced references");
}
'''
fixture = fixture.replace('@@IDENTITY@@', identity).replace('@@LOOKUP@@', lookup)
with tempfile.TemporaryDirectory(prefix='nm-display-identity-') as directory:
    p = Path(directory)
    (p / 'test.cpp').write_text(fixture)
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(p / 'test.cpp'), '-o', str(p / 'test')], check=True)
    subprocess.run([str(p / 'test')], check=True, timeout=20)
