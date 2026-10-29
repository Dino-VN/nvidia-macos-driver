#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <mach-o/loader.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <cstdio>
#include <cstring>
#include <stdexcept>

static NSFileManager *fm() {return NSFileManager.defaultManager;}
static void need(bool value,NSString *reason) {if(!value)throw std::runtime_error(reason.UTF8String);}
static NSString *absolute(const char *value) {
    NSString *path=@(value);need(path.isAbsolutePath,@"An absolute path is required");
    return path.stringByStandardizingPath.stringByResolvingSymlinksInPath;
}
static bool within(NSString *root,NSString *path) {return [path hasPrefix:[root stringByAppendingString:@"/"]];}
static NSString *inside(NSString *root,NSString *relative) {
    need([relative isKindOfClass:NSString.class] && relative.length && !relative.isAbsolutePath,@"Invalid package-relative path");
    need(![relative.pathComponents containsObject:@".."],@"Parent traversal in package path");
    NSString *path=[root stringByAppendingPathComponent:relative].stringByResolvingSymlinksInPath;
    need(within(root,path),@"Package path resolves outside the runtime");return path;
}
static bool exists(NSString *path) {struct stat s;return lstat(path.fileSystemRepresentation,&s)==0;}
static NSString *hashFile(NSString *path) {
    NSData *data=[NSData dataWithContentsOfFile:path options:NSDataReadingMappedIfSafe error:nil];
    need(data!=nil,[NSString stringWithFormat:@"Cannot read %@",path]);
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    need(data.length<=UINT32_MAX,@"Artifact is too large for this package schema");
    CC_SHA256(data.bytes,(CC_LONG)data.length,digest);
    NSMutableString *hex=[NSMutableString string];for(unsigned char byte:digest)[hex appendFormat:@"%02x",byte];return hex;
}
static NSDictionary *readJSON(NSString *path) {
    NSData *data=[NSData dataWithContentsOfFile:path];need(data!=nil,[NSString stringWithFormat:@"Missing %@",path]);
    id value=[NSJSONSerialization JSONObjectWithData:data options:NSJSONReadingMutableContainers error:nil];
    need([value isKindOfClass:NSDictionary.class],@"Malformed JSON metadata");return value;
}
static void writeJSON(NSString *path,id value) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];
    need(data!=nil && [data writeToFile:path options:NSDataWritingAtomic error:nil],@"Cannot write setup journal");
}
static void move(NSString *source,NSString *target) {NSError *error=nil;need([fm() moveItemAtPath:source toPath:target error:&error],error.description?:@"Cannot move file");}
static void remove(NSString *path) {if(exists(path)){NSError *error=nil;need([fm() removeItemAtPath:path error:&error],error.description?:@"Cannot remove setup file");}}
static void mkdir(NSString *path) {need([fm() createDirectoryAtPath:path withIntermediateDirectories:YES attributes:@{NSFilePosixPermissions:@0700} error:nil],@"Cannot create private directory");}
static void checkSignature(NSString *root,NSString *file) {
    NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:@"/usr/bin/codesign"];
    task.arguments=@[@"--verify",@"--strict",file];task.currentDirectoryURL=[NSURL fileURLWithPath:root];
    // Unread pipes can fill when a diagnostic Wine launch exports DYLD_PRINT_*
    // to child tools. Signature checks must not block waiting for those pipes.
    task.standardError=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];
    task.standardOutput=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];
    NSMutableDictionary *environment=[NSProcessInfo.processInfo.environment mutableCopy];
    for(NSString *key in environment.allKeys)if([key hasPrefix:@"DYLD_"])[environment removeObjectForKey:key];
    task.environment=environment;NSError *error=nil;
    need([task launchAndReturnError:&error],error.description?:@"Cannot inspect signature");[task waitUntilExit];
    need(task.terminationStatus==0,[NSString stringWithFormat:@"Invalid signature: %@",file]);
}
static void checkMach(NSString *file) {
    NSFileHandle *handle=[NSFileHandle fileHandleForReadingAtPath:file];NSData *data=[handle readDataOfLength:sizeof(mach_header_64)];[handle closeFile];
    mach_header_64 header{};need(data.length==sizeof header,@"Truncated Mach-O artifact");memcpy(&header,data.bytes,sizeof header);
    need(header.magic==MH_MAGIC_64 && header.cputype==CPU_TYPE_X86_64,@"Runtime needs Intel x64 Mach-O files");
}
static void checkPE(NSString *file) {
    NSFileHandle *handle=[NSFileHandle fileHandleForReadingAtPath:file];NSData *data=[handle readDataOfLength:64];
    need(data.length==64,@"Truncated graphics DLL");const auto *bytes=(const unsigned char *)data.bytes;
    need(bytes[0]=='M'&&bytes[1]=='Z',@"Graphics file is not a PE DLL");uint32_t offset=0;memcpy(&offset,bytes+60,4);
    need(offset<1024*1024,@"Invalid PE header offset");[handle seekToFileOffset:offset];data=[handle readDataOfLength:26];[handle closeFile];
    need(data.length==26,@"Truncated PE header");bytes=(const unsigned char *)data.bytes;
    need(bytes[0]=='P'&&bytes[1]=='E'&&bytes[2]==0&&bytes[3]==0&&bytes[4]==0x64&&bytes[5]==0x86&&bytes[24]==0x0b&&bytes[25]==0x02,@"Graphics DLL must be PE32+ x86_64");
}
static NSArray<NSString *> *dllNames(NSString *group) {
    if([group isEqual:@"dlss"])return @[@"nvapi64.dll",@"nvngx.dll",@"_nvngx.dll"];
    return [group isEqual:@"vkd3d"]?@[@"d3d12.dll",@"d3d12core.dll"]:@[@"d3d11.dll",@"dxgi.dll"];
}
static NSString *dllDirectory(NSString *group) {return [group stringByAppendingString:@"/x64"];}
static NSString *setupPath(NSString *prefix,NSString *group,NSString *suffix) {
    return [prefix stringByAppendingPathComponent:[NSString stringWithFormat:@".nvk-%@-%@",group,suffix]];
}
static NSDictionary *validate(NSString *root) {
    NSDictionary *manifest=readJSON([root stringByAppendingPathComponent:@"nvk-wine-runtime.json"]);
    need([manifest[@"schema_version"] intValue]==1 && [manifest[@"runtime_id"] isKindOfClass:NSString.class],@"Unsupported runtime manifest");
    NSDictionary *files=manifest[@"files"];need([files isKindOfClass:NSDictionary.class],@"Missing artifact hashes");
    bool provider=[manifest[@"kind"] isEqual:@"provider"];
    need(!provider||manifest[@"wine"]==nil,@"A provider-only runtime must not select a bundled Wine executable");
    NSMutableArray *native=[NSMutableArray arrayWithArray:@[manifest[@"entry"][@"path"]?:@"",manifest[@"renderer"][@"path"]?:@""]];
    if(!provider)[native addObject:manifest[@"wine"][@"executable"]?:@""];
    NSMutableArray *required=[native mutableCopy];
    [required addObjectsFromArray:@[@"bin/nvk-runtime",@"dxvk/x64/d3d11.dll",@"dxvk/x64/dxgi.dll"]];
    bool d3d12=manifest[@"vkd3d"]!=nil;
    if(d3d12){
        need([manifest[@"vkd3d"] isKindOfClass:NSDictionary.class],@"Invalid vkd3d-proton metadata");
        [required addObjectsFromArray:@[@"vkd3d/x64/d3d12.dll",@"vkd3d/x64/d3d12core.dll",@"VKD3D-BUILD.json",@"LICENSES/vkd3d-proton-LICENSE.txt",@"LICENSES/vkd3d-proton-COPYING.txt"]];
    }
    bool dlss=manifest[@"dlss"]!=nil;
    if(dlss){
        need(d3d12&&[manifest[@"dlss"] isKindOfClass:NSDictionary.class]
             &&[manifest[@"presentation"][@"wine_child_options"] intValue]==1,@"DLSS requires D3D12 and Wine child-process option forwarding");
        [required addObjectsFromArray:@[@"dlss/x64/nvapi64.dll",@"dlss/x64/nvngx.dll",@"dlss/x64/_nvngx.dll",@"DLSS-BUILD.json",@"LICENSES/NVIDIA-NGX-driver-license.txt",@"LICENSES/DXVK-NVAPI-MIT.txt"]];
    }
    for(NSString *relative in required)need(files[relative]!=nil,@"Required artifact missing from manifest hashes");
    for(NSString *relative in files){NSString *path=inside(root,relative);need([files[relative] isEqualToString:hashFile(path)],[NSString stringWithFormat:@"SHA-256 mismatch: %@",relative]);}
    [native addObject:@"bin/nvk-runtime"];
    for(NSString *relative in native){
        NSString *path=inside(root,relative);checkMach(path);checkSignature(root,path);
    }
    need([inside(root,@"lib/libMoltenVK.dylib") isEqualToString:inside(root,manifest[@"entry"][@"path"])],@"Private Wine Vulkan alias is missing or points at another provider");
    for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"])checkPE(inside(root,[@"dxvk/x64" stringByAppendingPathComponent:name]));
    if(d3d12)for(NSString *name in dllNames(@"vkd3d"))checkPE(inside(root,[dllDirectory(@"vkd3d") stringByAppendingPathComponent:name]));
    if(dlss)for(NSString *name in dllNames(@"dlss"))checkPE(inside(root,[dllDirectory(@"dlss") stringByAppendingPathComponent:name]));
    return manifest;
}
static NSString *system32(NSString *prefix) {
    NSString *path=[prefix stringByAppendingPathComponent:@"drive_c/windows/system32"].stringByResolvingSymlinksInPath;
    BOOL directory=NO;need(within(prefix,path)&&[fm() fileExistsAtPath:path isDirectory:&directory]&&directory,@"Initialize the dedicated Wine prefix first; its system32 must stay within the prefix");return path;
}
static void preflightRestore(NSString *prefix,NSDictionary *state,NSString *group) {
    NSString *dir=system32(prefix),*backups=setupPath(prefix,group,@"originals");
    NSDictionary *files=state[@"files"];need([files isKindOfClass:NSDictionary.class],@"Invalid DLL journal");
    need([state[@"schema_version"] intValue]==1&&files.count==dllNames(group).count,@"Unsupported DLL journal");
    need([@[@"prepared",@"installed",@"restoring"] containsObject:state[@"phase"]],@"Invalid DLL setup phase");
    need(within(prefix,backups.stringByResolvingSymlinksInPath),@"DLL backup directory resolves outside this prefix");
    bool prepared=[state[@"phase"] isEqualToString:@"prepared"]||[state[@"phase"] isEqualToString:@"restoring"];
    for(NSString *name in dllNames(group)){
        NSDictionary *item=files[name];need([item isKindOfClass:NSDictionary.class],@"Incomplete DLL journal");NSString *path=[dir stringByAppendingPathComponent:name],*old=[backups stringByAppendingPathComponent:name];
        if(exists(path)){
            NSString *current=hashFile(path);bool original=prepared&&!exists(old)&&[current isEqualToString:item[@"original_sha256"]];
            need(original||[current isEqualToString:item[@"installed_sha256"]],@"A DLL changed after setup; refusing to overwrite it during rollback");
        }
        if(exists(old))need([item[@"original_exists"] boolValue]&&[hashFile(old) isEqualToString:item[@"original_sha256"]],@"Original DLL backup changed; refusing rollback");
        if([item[@"original_exists"] boolValue]&&!exists(old))need(prepared&&exists(path)&&[hashFile(path) isEqualToString:item[@"original_sha256"]],@"Original DLL backup is missing");
    }
}
static void restore(NSString *prefix,NSDictionary *state,NSString *group) {
    preflightRestore(prefix,state,group);
    NSString *dir=system32(prefix),*backups=setupPath(prefix,group,@"originals");
    NSDictionary *files=state[@"files"];
    // All entries are checked before either file is changed.
    NSMutableDictionary *restoring=[state mutableCopy];restoring[@"phase"]=@"restoring";
    writeJSON(setupPath(prefix,group,@"state.json"),restoring);
    for(NSString *name in dllNames(group)){
        NSDictionary *item=files[name];NSString *path=[dir stringByAppendingPathComponent:name],*old=[backups stringByAppendingPathComponent:name];
        if(exists(old)){remove(path);move(old,path);}
        else if(![item[@"original_exists"] boolValue])remove(path);
    }
    remove(backups);remove(setupPath(prefix,group,@"state.json"));
}
static NSDictionary *readState(NSString *prefix,NSString *group) {
    NSString *journal=setupPath(prefix,group,@"state.json");
    if(!exists(journal))return nil;
    struct stat info{};need(lstat(journal.fileSystemRepresentation,&info)==0&&S_ISREG(info.st_mode),@"DLL journal must be a regular file");
    return readJSON(journal);
}
static void install(NSString *root,NSString *prefix,NSDictionary *manifest,NSString *group,NSDictionary *extra=nil) {
    NSString *dir=system32(prefix),*journal=setupPath(prefix,group,@"state.json");
    if(exists(journal)){
        struct stat journalInfo{};need(lstat(journal.fileSystemRepresentation,&journalInfo)==0&&!S_ISLNK(journalInfo.st_mode),@"DLL journal must not be a symbolic link");
        NSDictionary *old=readState(prefix,group);
        preflightRestore(prefix,old,group);
        need([old[@"phase"] isEqualToString:@"installed"],@"Restore the interrupted DLL setup before selecting another runtime");
        for(NSString *name in dllNames(group)){
            NSString *relative=[dllDirectory(group) stringByAppendingPathComponent:name];
            NSDictionary *item=old[@"files"][name];
            need([item[@"installed_sha256"] isEqual:manifest[@"files"][relative]],@"Restore the previous DLL setup before selecting a different graphics pair");
            need([hashFile([dir stringByAppendingPathComponent:name]) isEqualToString:item[@"installed_sha256"]],@"Installed graphics DLL changed");
        }
        // A bundled runtime and the installed driver provider can contain the
        // exact same DLL pair. Adopt its identity without replacing DLLs or
        // losing the original rollback journal/backups.
        if(![old[@"runtime_id"] isEqual:manifest[@"runtime_id"]]){
            NSMutableDictionary *adopted=[old mutableCopy];adopted[@"runtime_id"]=manifest[@"runtime_id"];
            writeJSON(journal,adopted);
        }
        return;
    }
    NSString *backups=setupPath(prefix,group,@"originals");
    need(!exists(backups),@"Unclaimed DLL backups exist; inspect them before setup");
    NSMutableDictionary *files=[NSMutableDictionary dictionary];
    for(NSString *name in dllNames(group)){
        NSString *path=[dir stringByAppendingPathComponent:name],*relative=[dllDirectory(group) stringByAppendingPathComponent:name];
        files[name]=@{@"original_exists":@(exists(path)),@"original_sha256":exists(path)?hashFile(path):@"",@"installed_sha256":manifest[@"files"][relative]};
    }
    NSMutableDictionary *state=[@{@"schema_version":@1,@"runtime_id":manifest[@"runtime_id"],@"phase":@"prepared",@"files":files} mutableCopy];
    if(extra)[state addEntriesFromDictionary:extra];
    NSString *stage=setupPath(prefix,group,[@"stage-" stringByAppendingString:NSUUID.UUID.UUIDString]);
    mkdir(stage);mkdir(backups);writeJSON(journal,state);
    try{
        for(NSString *name in dllNames(group)){
            NSString *temporary=[stage stringByAppendingPathComponent:name];
            need([fm() copyItemAtPath:inside(root,[dllDirectory(group) stringByAppendingPathComponent:name]) toPath:temporary error:nil],@"Cannot stage graphics DLL");
            need([hashFile(temporary) isEqualToString:files[name][@"installed_sha256"]],@"Staged DLL checksum mismatch");
        }
        for(NSString *name in dllNames(group)){
            NSString *path=[dir stringByAppendingPathComponent:name];if(exists(path))move(path,[backups stringByAppendingPathComponent:name]);move([stage stringByAppendingPathComponent:name],path);
        }
        state[@"phase"]=@"installed";writeJSON(journal,state);remove(stage);
    }catch(...){restore(prefix,state,group);remove(stage);throw;}
}
// Registry values are exported/imported using Wine's own reg.exe, so bottles,
// Unicode paths and non-string original value types retain their exact data.
// Only FullPath is restored; unrelated NGX settings are never overwritten.
static NSString *ngxKey=@"HKEY_LOCAL_MACHINE\\SOFTWARE\\NVIDIA Corporation\\Global\\NGXCore";
static NSString *ownedRegistryValue=@"\"FullPath\"=\"C:\\\\windows\\\\system32\"";
static bool registryValueValid(id value) {
    if(value==NSNull.null)return true;
    if(![value isKindOfClass:NSString.class])return false;
    NSArray<NSString *> *lines=[value componentsSeparatedByString:@"\n"];
    if(![lines.firstObject hasPrefix:@"\"FullPath\"="]||[lines.firstObject isEqual:@"\"FullPath\"=-"])return false;
    NSCharacterSet *hex=[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdefABCDEF,\\ \t"];
    for(NSUInteger i=1;i<lines.count;i++)
        if(![lines[i-1] hasSuffix:@"\\"]||[lines[i] rangeOfCharacterFromSet:hex.invertedSet].location!=NSNotFound)return false;
    return ![lines.lastObject hasSuffix:@"\\"];
}
static id registryValue(NSString *text) {
    bool section=false;NSArray<NSString *> *lines=[[text stringByReplacingOccurrencesOfString:@"\r" withString:@""] componentsSeparatedByString:@"\n"];
    NSString *target=[NSString stringWithFormat:@"[%@]",ngxKey];
    for(NSUInteger i=0;i<lines.count;i++){
        NSString *line=lines[i];
        if([line hasPrefix:@"["])section=[line caseInsensitiveCompare:target]==NSOrderedSame;
        if(!section||line.length<11||[[line substringToIndex:11] caseInsensitiveCompare:@"\"FullPath\"="]!=NSOrderedSame)continue;
        NSMutableString *block=[[@"\"FullPath\"=" stringByAppendingString:[line substringFromIndex:11]] mutableCopy];
        while([line hasSuffix:@"\\"]){need(++i<lines.count,@"Truncated registry value export");line=lines[i];[block appendFormat:@"\n%@",line];}
        need(registryValueValid(block),@"Invalid registry export value");return block;
    }
    return NSNull.null;
}
struct WineRegistry {
    NSString *__strong root,*__strong prefix,*__strong executable;
    NSArray<NSString *> *__strong arguments;
    NSDictionary *run(NSArray<NSString *> *command,NSString *scratch) const {
        NSString *output=[scratch stringByAppendingPathComponent:NSUUID.UUID.UUIDString];
        need([fm() createFileAtPath:output contents:nil attributes:@{NSFilePosixPermissions:@0600}],@"Cannot create registry command log");
        NSFileHandle *handle=[NSFileHandle fileHandleForWritingAtPath:output];
        NSTask *task=[NSTask new];task.executableURL=[NSURL fileURLWithPath:executable];task.arguments=[arguments arrayByAddingObjectsFromArray:command];
        task.currentDirectoryURL=[NSURL fileURLWithPath:prefix];task.standardOutput=handle;
        task.standardError=[NSFileHandle fileHandleForWritingAtPath:@"/dev/null"];
        NSMutableDictionary *env=[NSProcessInfo.processInfo.environment mutableCopy];
        for(NSString *key in env.allKeys)if([key hasPrefix:@"DYLD_PRINT_"])[env removeObjectForKey:key];
        env[@"WINEPREFIX"]=prefix;env[@"DYLD_LIBRARY_PATH"]=[root stringByAppendingPathComponent:@"lib"];
        env[@"WINEDEBUG"]=@"-all";env[@"DXVK_HUD"]=@"0";env[@"WINE_NVK_HUD"]=@"0";
        task.environment=env;NSError *error=nil;
        need([task launchAndReturnError:&error],error.description?:@"Cannot launch the selected Wine");
        NSDate *deadline=[NSDate dateWithTimeIntervalSinceNow:60];
        while(task.running&&deadline.timeIntervalSinceNow>0)usleep(10000);
        if(task.running){[task terminate];usleep(200000);if(task.running)kill(task.processIdentifier,SIGKILL);[task waitUntilExit];[handle closeFile];remove(output);need(false,@"Wine registry command timed out; close applications in this prefix and retry");}
        [task waitUntilExit];[handle closeFile];NSData *data=[NSData dataWithContentsOfFile:output];remove(output);
        NSString *text=[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]?:@"";
        return @{@"status":@(task.terminationStatus),@"output":text};
    }
    void verify(NSString *scratch) const {
        need([fm() isExecutableFileAtPath:executable],@"The selected Wine executable is missing");
        NSDictionary *result=run(@[@"winepath.exe",@"-u",@"C:\\windows\\system32"],scratch);
        NSString *path=[result[@"output"] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
        need([result[@"status"] intValue]==0&&[path.stringByResolvingSymlinksInPath isEqual:system32(prefix)],@"Selected Wine/bottle does not resolve to the requested prefix; use its Open Shell and matching --bottle arguments");
    }
    id read(NSString *scratch) const {
        NSString *file=[scratch stringByAppendingPathComponent:@"registry-export.reg"];
        NSString *windows=[@"Z:" stringByAppendingString:[file stringByReplacingOccurrencesOfString:@"/" withString:@"\\"]];
        // An ancestor export distinguishes an absent target key/value from a
        // registry read failure without parsing localized command messages.
        for(NSString *key in @[ngxKey,@"HKEY_LOCAL_MACHINE\\SOFTWARE\\NVIDIA Corporation\\Global",@"HKEY_LOCAL_MACHINE\\SOFTWARE\\NVIDIA Corporation",@"HKEY_LOCAL_MACHINE\\SOFTWARE"]){
            remove(file);NSDictionary *result=run(@[@"reg.exe",@"export",key,windows,@"/y"],scratch);
            if([result[@"status"] intValue])continue;
            NSData *data=[NSData dataWithContentsOfFile:file];need(data&&data.length<64*1024*1024,@"Invalid registry export size");
            NSString *text=[[NSString alloc] initWithData:data encoding:NSUTF16StringEncoding];
            if(!text)text=[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
            need(text&&[text containsString:@"Windows Registry Editor"],@"Cannot decode Wine registry export");
            id value=registryValue(text);remove(file);return value;
        }
        need(false,@"Cannot read registry in the selected Wine prefix");return nil;
    }
    void write(id value,NSString *scratch) const {
        need(registryValueValid(value),@"Malformed original registry value in DLSS journal");
        NSString *text=[NSString stringWithFormat:@"Windows Registry Editor Version 5.00\r\n\r\n[%@]\r\n%@\r\n",ngxKey,value==NSNull.null?@"\"FullPath\"=-":value];
        NSString *file=[scratch stringByAppendingPathComponent:@"registry-import.reg"];
        NSData *data=[text dataUsingEncoding:NSUTF16StringEncoding];need([data writeToFile:file atomically:YES],@"Cannot stage registry restore");
        NSString *windows=[@"Z:" stringByAppendingString:[file stringByReplacingOccurrencesOfString:@"/" withString:@"\\"]];
        NSDictionary *result=run(@[@"reg.exe",@"import",windows],scratch);remove(file);
        need([result[@"status"] intValue]==0&&[read(scratch) isEqual:value],@"NGX registry update did not complete; the DLSS rollback journal is retained");
    }
};
static void preflightDLSS(NSString *prefix,NSDictionary *state,const WineRegistry &wine,NSString *scratch) {
    preflightRestore(prefix,state,@"dlss");id original=state[@"registry_original"];
    need(registryValueValid(original),@"Invalid original registry value in DLSS journal");
    need([@[@"prepared",@"installed",@"restoring"] containsObject:state[@"registry_phase"]],@"Invalid DLSS registry phase");
    id current=wine.read(scratch);bool pending=![state[@"registry_phase"] isEqual:@"installed"]||[state[@"phase"] isEqual:@"restoring"];
    need([current isEqual:ownedRegistryValue]||(pending&&[current isEqual:original]),@"NGX FullPath changed after setup; refusing to overwrite it during rollback");
}
static void restoreDLSS(NSString *prefix,NSDictionary *state,const WineRegistry &wine,NSString *scratch) {
    if(!state)return;
    preflightDLSS(prefix,state,wine,scratch);NSMutableDictionary *restoring=[state mutableCopy];
    restoring[@"phase"]=@"restoring";restoring[@"registry_phase"]=@"restoring";writeJSON(setupPath(prefix,@"dlss",@"state.json"),restoring);
    if(![wine.read(scratch) isEqual:state[@"registry_original"]])wine.write(state[@"registry_original"],scratch);
    restore(prefix,restoring,@"dlss");
}
static void installDLSS(NSString *root,NSString *prefix,NSDictionary *manifest,const WineRegistry &wine,NSString *scratch) {
    need(manifest[@"dlss"]!=nil,@"This provider does not include NGX/NVAPI; update the driver runtime for DLSS");
    NSDictionary *old=readState(prefix,@"dlss");id original=nil;
    if(old){preflightDLSS(prefix,old,wine,scratch);need([old[@"registry_phase"] isEqual:@"installed"],@"Restore the interrupted DLSS setup before reinstalling");original=old[@"registry_original"];}
    else original=wine.read(scratch);
    bool hadDXVK=readState(prefix,@"dxvk")!=nil,hadVKD3D=readState(prefix,@"vkd3d")!=nil;
    try{
        install(root,prefix,manifest,@"dxvk");install(root,prefix,manifest,@"vkd3d");
        install(root,prefix,manifest,@"dlss",@{@"registry_original":original,@"registry_phase":@"prepared"});
        if(!old){
            wine.write(ownedRegistryValue,scratch);
            NSMutableDictionary *state=[readState(prefix,@"dlss") mutableCopy];state[@"registry_phase"]=@"installed";writeJSON(setupPath(prefix,@"dlss",@"state.json"),state);
        }
    }catch(...){
        if(!old)restoreDLSS(prefix,readState(prefix,@"dlss"),wine,scratch);
        if(!hadVKD3D)if(NSDictionary *state=readState(prefix,@"vkd3d"))restore(prefix,state,@"vkd3d");
        if(!hadDXVK)if(NSDictionary *state=readState(prefix,@"dxvk"))restore(prefix,state,@"dxvk");
        throw;
    }
}
int main(int argc,char **argv){@autoreleasepool{
    int status=0;NSMutableDictionary *result=[NSMutableDictionary dictionary];int lock=-1;NSString *scratch=nil;
    try{
        need(argc>=3,@"Usage: nvk-runtime check ROOT | install[-d3d12] ROOT PREFIX | install-dlss ROOT PREFIX WINE [WINE_ARGS...] | restore[-dlss] ROOT PREFIX [WINE [WINE_ARGS...]]");
        NSString *command=@(argv[1]),*root=absolute(argv[2]);
        need([@[@"check",@"install",@"install-d3d12",@"install-dlss",@"restore",@"restore-dlss"] containsObject:command],@"Unknown setup command");
        bool restoring=[command isEqual:@"restore"]||[command isEqual:@"restore-dlss"];
        NSDictionary *manifest=restoring?nil:validate(root);
        if([command isEqualToString:@"check"]){
            need(argc==3,@"check takes only the runtime root");
            result[@"runtime_id"]=manifest[@"runtime_id"];
            result[@"supports_d3d12"]=@(manifest[@"vkd3d"]!=nil);
            result[@"supports_dlss"]=@(manifest[@"dlss"]!=nil);
            result[@"supports_hud"]=@([manifest[@"presentation"][@"hud"] isEqual:@"gpu-copy-cached-bitmap"]);
            if(manifest[@"wine"][@"executable"])result[@"wine_executable"]=inside(root,manifest[@"wine"][@"executable"]);
            else result[@"kind"]=@"provider";
        }else{
            need(argc>=4,@"A dedicated prefix is required");NSString *prefix=absolute(argv[3]);system32(prefix);
            lock=open([prefix stringByAppendingPathComponent:@".nvk-dxvk.lock"].fileSystemRepresentation,O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
            need(lock>=0&&flock(lock,LOCK_EX|LOCK_NB)==0,@"Another setup operation is using this prefix");
            NSDictionary *dlss=readState(prefix,@"dlss");
            bool needsWine=[command isEqual:@"install-dlss"]||(restoring&&dlss!=nil);
            WineRegistry wine{};
            if(needsWine){
                need(argc>=5,@"DLSS install/restore requires the matching Wine executable and optional --bottle arguments");
                NSMutableArray *args=[NSMutableArray array];for(int i=5;i<argc;i++)[args addObject:@(argv[i])];
                wine={root,prefix,absolute(argv[4]),args};
                scratch=[prefix stringByAppendingPathComponent:[@".nvk-registry-" stringByAppendingString:NSUUID.UUID.UUIDString]];mkdir(scratch);wine.verify(scratch);
            }else need(argc==4||(restoring&&argc>=5),@"Unexpected arguments for this setup command");
            if([command isEqualToString:@"install"])install(root,prefix,manifest,@"dxvk");
            else if([command isEqualToString:@"install-d3d12"]){
                need(manifest[@"vkd3d"]!=nil,@"This provider does not include vkd3d-proton; update the driver runtime for D3D12");
                bool hadDXVK=readState(prefix,@"dxvk")!=nil;
                install(root,prefix,manifest,@"dxvk");
                try{install(root,prefix,manifest,@"vkd3d");}catch(...){
                    if(!hadDXVK)restore(prefix,readState(prefix,@"dxvk"),@"dxvk");
                    throw;
                }
            }else if([command isEqual:@"install-dlss"]){
                installDLSS(root,prefix,manifest,wine,scratch);
            }else if([command isEqual:@"restore-dlss"]){
                restoreDLSS(prefix,dlss,wine,scratch);
            }else{
                NSDictionary *dxvk=readState(prefix,@"dxvk"),*vkd3d=readState(prefix,@"vkd3d");
                // Check every component and registry value before restoring any.
                if(dxvk)preflightRestore(prefix,dxvk,@"dxvk");
                if(vkd3d)preflightRestore(prefix,vkd3d,@"vkd3d");
                if(dlss)preflightDLSS(prefix,dlss,wine,scratch);
                if(dlss)restoreDLSS(prefix,dlss,wine,scratch);
                if(vkd3d)restore(prefix,vkd3d,@"vkd3d");
                if(dxvk)restore(prefix,dxvk,@"dxvk");
            }
            result[@"prefix"]=prefix;
        }
        result[@"result"]=@"PASS";result[@"command"]=command;
    }catch(const std::exception &error){result[@"result"]=@"FAIL";result[@"error"]=@(error.what());status=1;}
    if(scratch)[fm() removeItemAtPath:scratch error:nil];
    if(lock>=0)close(lock);
    NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];fwrite(json.bytes,1,json.length,stdout);putchar('\n');return status;
}}
