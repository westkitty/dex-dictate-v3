import os
import sys
import shutil

print("--- VERIFYING SYSTEM ---")
all_good = True

# 1. Check Input Group
groups = os.getgroups()
# Need to find gid for 'input'
try:
    import grp
    input_gid = grp.getgrnam('input').gr_gid
    if input_gid not in groups:
        print("❌ FATAL: REBOOT REQUIRED. Input permissions not active.")
        all_good = False
    else:
        print("✅ User is in 'input' group.")
except:
    print("⚠️ Could not verify input group.")

# 2. Check UInput Access
if os.access('/dev/uinput', os.W_OK):
    print("✅ /dev/uinput is writable.")
else:
    print("❌ /dev/uinput is NOT writable.")
    all_good = False

# 3. Check Tools
if shutil.which('wl-clipboard') or shutil.which('wl-copy'):
    print("✅ wl-clipboard found.")
else:
    print("❌ wl-clipboard NOT found.")
    all_good = False

if shutil.which('ffmpeg'):
    print("✅ ffmpeg found.")
else:
    print("❌ ffmpeg NOT found.")
    all_good = False

# 4. Check Preload
if os.path.exists(os.path.join(os.path.expanduser("~"), ".cache", "torch", "hub", "snakers4_silero-vad_master")):
    print("✅ Silero VAD cached.")
else:
    print("⚠️ Silero VAD might not be cached.")

if all_good:
    print("\n✅ SYSTEM VERIFIED: PASS")
else:
    print("\n❌ SYSTEM VERIFICATION FAILED")
