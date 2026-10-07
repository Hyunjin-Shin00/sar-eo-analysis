import sys
import os

print(f"Python executable: {sys.executable}")
print(f"Python version: {sys.version}")

try:
    from osgeo import gdal
    print(f"✅ GDAL: {gdal.__version__}")
except ImportError as e:
    print(f"❌ GDAL Import Failed: {e}")

try:
    import torch
    print(f"✅ Torch: {torch.__version__}")
except ImportError as e:
    print(f"❌ Torch Import Failed: {e}")

try:
    import lightglue
    print(f"✅ LightGlue: Installed (version check usually fails for git install)")
except ImportError as e:
    print(f"❌ LightGlue Import Failed: {e}")

try:
    import rpcm
    print(f"✅ rpcm: Installed")
except ImportError as e:
    print(f"❌ rpcm Import Failed: {e}")

# Check local package import
try:
    # Add current directory to path if needed (though running from here should work)
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.append(cwd)
    import geometric_correction
    print("✅ geometric_correction (local package): Imported successfully")
except ImportError as e:
    print(f"❌ geometric_correction Import Failed: {e}")
