#import <Foundation/Foundation.h>
#include <CommonCrypto/CommonDigest.h>
#include <mach-o/loader.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
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
    task.standardError=[NSPipe pipe];task.standardOutput=[NSPipe pipe];NSError *error=nil;
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
    need(data.length==64,@"Truncated DXVK DLL");const auto *bytes=(const unsigned char *)data.bytes;
    need(bytes[0]=='M'&&bytes[1]=='Z',@"DXVK file is not a PE DLL");uint32_t offset=0;memcpy(&offset,bytes+60,4);
    need(offset<1024*1024,@"Invalid PE header offset");[handle seekToFileOffset:offset];data=[handle readDataOfLength:26];[handle closeFile];
    need(data.length==26,@"Truncated PE header");bytes=(const unsigned char *)data.bytes;
    need(bytes[0]=='P'&&bytes[1]=='E'&&bytes[2]==0&&bytes[3]==0&&bytes[4]==0x64&&bytes[5]==0x86&&bytes[24]==0x0b&&bytes[25]==0x02,@"DXVK DLL must be PE32+ x86_64");
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
    for(NSString *relative in required)need(files[relative]!=nil,@"Required artifact missing from manifest hashes");
    for(NSString *relative in files){NSString *path=inside(root,relative);need([files[relative] isEqualToString:hashFile(path)],[NSString stringWithFormat:@"SHA-256 mismatch: %@",relative]);}
    [native addObject:@"bin/nvk-runtime"];
    for(NSString *relative in native){
        NSString *path=inside(root,relative);checkMach(path);checkSignature(root,path);
    }
    need([inside(root,@"lib/libMoltenVK.dylib") isEqualToString:inside(root,manifest[@"entry"][@"path"])],@"Private Wine Vulkan alias is missing or points at another provider");
    for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"])checkPE(inside(root,[@"dxvk/x64" stringByAppendingPathComponent:name]));
    return manifest;
}
static NSString *system32(NSString *prefix) {
    NSString *path=[prefix stringByAppendingPathComponent:@"drive_c/windows/system32"].stringByResolvingSymlinksInPath;
    BOOL directory=NO;need(within(prefix,path)&&[fm() fileExistsAtPath:path isDirectory:&directory]&&directory,@"Initialize the dedicated Wine prefix first; its system32 must stay within the prefix");return path;
}
static void restore(NSString *prefix,NSDictionary *state) {
    NSString *dir=system32(prefix),*backups=[prefix stringByAppendingPathComponent:@".nvk-dxvk-originals"];
    NSDictionary *files=state[@"files"];need([files isKindOfClass:NSDictionary.class],@"Invalid DLL journal");
    need(within(prefix,backups.stringByResolvingSymlinksInPath),@"DLL backup directory resolves outside this prefix");
    bool prepared=[state[@"phase"] isEqualToString:@"prepared"]||[state[@"phase"] isEqualToString:@"restoring"];
    for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
        NSDictionary *item=files[name];need([item isKindOfClass:NSDictionary.class],@"Incomplete DLL journal");NSString *path=[dir stringByAppendingPathComponent:name],*old=[backups stringByAppendingPathComponent:name];
        if(exists(path)){
            NSString *current=hashFile(path);bool original=prepared&&!exists(old)&&[current isEqualToString:item[@"original_sha256"]];
            need(original||[current isEqualToString:item[@"installed_sha256"]],@"A DLL changed after setup; refusing to overwrite it during rollback");
        }
        if(exists(old))need([item[@"original_exists"] boolValue]&&[hashFile(old) isEqualToString:item[@"original_sha256"]],@"Original DLL backup changed; refusing rollback");
        if([item[@"original_exists"] boolValue]&&!exists(old))need(prepared&&exists(path)&&[hashFile(path) isEqualToString:item[@"original_sha256"]],@"Original DLL backup is missing");
    }
    // All entries are checked before either file is changed.
    NSMutableDictionary *restoring=[state mutableCopy];restoring[@"phase"]=@"restoring";
    writeJSON([prefix stringByAppendingPathComponent:@".nvk-dxvk-state.json"],restoring);
    for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
        NSDictionary *item=files[name];NSString *path=[dir stringByAppendingPathComponent:name],*old=[backups stringByAppendingPathComponent:name];
        if(exists(old)){remove(path);move(old,path);}
        else if(![item[@"original_exists"] boolValue])remove(path);
    }
    remove(backups);remove([prefix stringByAppendingPathComponent:@".nvk-dxvk-state.json"]);
}
static void install(NSString *root,NSString *prefix,NSDictionary *manifest) {
    NSString *dir=system32(prefix),*journal=[prefix stringByAppendingPathComponent:@".nvk-dxvk-state.json"];
    if(exists(journal)){
        struct stat journalInfo{};need(lstat(journal.fileSystemRepresentation,&journalInfo)==0&&!S_ISLNK(journalInfo.st_mode),@"DLL journal must not be a symbolic link");
        NSDictionary *old=readJSON(journal);
        need([old[@"phase"] isEqualToString:@"installed"],@"Restore the interrupted DLL setup before selecting another runtime");
        for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
            NSString *relative=[@"dxvk/x64" stringByAppendingPathComponent:name];
            NSDictionary *item=old[@"files"][name];
            need([item[@"installed_sha256"] isEqual:manifest[@"files"][relative]],@"Restore the previous DLL setup before selecting a different DXVK pair");
            need([hashFile([dir stringByAppendingPathComponent:name]) isEqualToString:item[@"installed_sha256"]],@"Installed DXVK DLL changed");
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
    NSString *backups=[prefix stringByAppendingPathComponent:@".nvk-dxvk-originals"];
    need(!exists(backups),@"Unclaimed DLL backups exist; inspect them before setup");
    NSMutableDictionary *files=[NSMutableDictionary dictionary];
    for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
        NSString *path=[dir stringByAppendingPathComponent:name],*relative=[@"dxvk/x64" stringByAppendingPathComponent:name];
        files[name]=@{@"original_exists":@(exists(path)),@"original_sha256":exists(path)?hashFile(path):@"",@"installed_sha256":manifest[@"files"][relative]};
    }
    NSMutableDictionary *state=[@{@"schema_version":@1,@"runtime_id":manifest[@"runtime_id"],@"phase":@"prepared",@"files":files} mutableCopy];
    NSString *stage=[prefix stringByAppendingPathComponent:[@".nvk-dxvk-stage-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    mkdir(stage);mkdir(backups);writeJSON(journal,state);
    try{
        for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
            NSString *temporary=[stage stringByAppendingPathComponent:name];
            need([fm() copyItemAtPath:inside(root,[@"dxvk/x64" stringByAppendingPathComponent:name]) toPath:temporary error:nil],@"Cannot stage DXVK DLL");
            need([hashFile(temporary) isEqualToString:files[name][@"installed_sha256"]],@"Staged DLL checksum mismatch");
        }
        for(NSString *name in @[@"d3d11.dll",@"dxgi.dll"]){
            NSString *path=[dir stringByAppendingPathComponent:name];if(exists(path))move(path,[backups stringByAppendingPathComponent:name]);move([stage stringByAppendingPathComponent:name],path);
        }
        state[@"phase"]=@"installed";writeJSON(journal,state);remove(stage);
    }catch(...){restore(prefix,state);remove(stage);throw;}
}
int main(int argc,char **argv){@autoreleasepool{
    int status=0;NSMutableDictionary *result=[NSMutableDictionary dictionary];int lock=-1;
    try{
        need(argc==3||argc==4,@"Usage: nvk-runtime check ROOT | install ROOT PREFIX | restore ROOT PREFIX");
        NSString *command=@(argv[1]),*root=absolute(argv[2]);
        need([command isEqualToString:@"check"]||[command isEqualToString:@"install"]||[command isEqualToString:@"restore"],@"Unknown setup command");
        NSDictionary *manifest=[command isEqualToString:@"restore"]?nil:validate(root);
        if([command isEqualToString:@"check"]){
            result[@"runtime_id"]=manifest[@"runtime_id"];
            if(manifest[@"wine"][@"executable"])result[@"wine_executable"]=inside(root,manifest[@"wine"][@"executable"]);
            else result[@"kind"]=@"provider";
        }else{
            need(argc==4,@"A dedicated prefix is required");NSString *prefix=absolute(argv[3]);system32(prefix);
            lock=open([prefix stringByAppendingPathComponent:@".nvk-dxvk.lock"].fileSystemRepresentation,O_CREAT|O_RDWR|O_CLOEXEC|O_NOFOLLOW,0600);
            need(lock>=0&&flock(lock,LOCK_EX|LOCK_NB)==0,@"Another setup operation is using this prefix");
            if([command isEqualToString:@"install"])install(root,prefix,manifest);
            else{NSString *journal=[prefix stringByAppendingPathComponent:@".nvk-dxvk-state.json"];if(exists(journal)){
                struct stat journalInfo{};need(lstat(journal.fileSystemRepresentation,&journalInfo)==0&&!S_ISLNK(journalInfo.st_mode),@"DLL journal must not be a symbolic link");
                restore(prefix,readJSON(journal));
            }}
            result[@"prefix"]=prefix;
        }
        result[@"result"]=@"PASS";result[@"command"]=command;
    }catch(const std::exception &error){result[@"result"]=@"FAIL";result[@"error"]=@(error.what());status=1;}
    if(lock>=0)close(lock);
    NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];fwrite(json.bytes,1,json.length,stdout);putchar('\n');return status;
}}
