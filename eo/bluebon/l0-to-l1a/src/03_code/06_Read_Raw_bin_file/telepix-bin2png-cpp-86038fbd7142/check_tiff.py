import numpy as np
import matplotlib.pyplot as plt
from tifffile import TiffFile
import os

def analyze_tiff(tiff_path):
    # Open the TIFF file
    with TiffFile(tiff_path) as tif:
        # Read the image data
        img = tif.asarray()
        
        # Get basic information
        print(f"\nFile: {os.path.basename(tiff_path)}")
        print(f"Image shape: {img.shape}")
        print(f"Data type: {img.dtype}")
        print(f"Min value: {np.min(img)}")
        print(f"Max value: {np.max(img)}")
        print(f"Mean value: {np.mean(img):.2f}")
        print(f"Standard deviation: {np.std(img):.2f}")
        
        # Create a figure with two subplots
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 5))
        
        # Display the image
        im = ax1.imshow(img, cmap='gray')
        ax1.set_title('TIFF Image')
        plt.colorbar(im, ax=ax1, label='Pixel Value')
        
        # Create histogram
        ax2.hist(img.flatten(), bins=100, range=(0, 4095))  # 12-bit range: 0-4095
        ax2.set_title('Histogram')
        ax2.set_xlabel('Pixel Value')
        ax2.set_ylabel('Frequency')
        
        plt.tight_layout()
        plt.show()

def main():
    # Directory containing TIFF files
    result_dir = "result"
    
    # Check if directory exists
    if not os.path.exists(result_dir):
        print(f"Directory '{result_dir}' does not exist!")
        return
    
    # Get all TIFF files in the directory
    tiff_files = [f for f in os.listdir(result_dir) if f.endswith('.tiff')]
    
    if not tiff_files:
        print(f"No TIFF files found in '{result_dir}' directory!")
        return
    
    # Process each TIFF file
    for tiff_file in tiff_files:
        file_path = os.path.join(result_dir, tiff_file)
        analyze_tiff(file_path)

if __name__ == "__main__":
    main() 