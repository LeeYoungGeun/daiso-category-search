import subprocess, os
os.chdir(r"c:\Users\301\dev\daiso-category-search")

files = [".env", ".env.live", ".env.local", 
         "backend/daisoproject-sst.json", 
         "backend/database/products.db"]

for f in files:
    r = subprocess.run(["git", "rm", "--cached", f], 
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  ✅ untracked: {f}")
    else:
        err = r.stderr.strip()
        if "did not match" in err:
            print(f"  ⏭️  not tracked: {f}")
        else:
            print(f"  ❌ error: {f} → {err}")

print("\nDONE")
