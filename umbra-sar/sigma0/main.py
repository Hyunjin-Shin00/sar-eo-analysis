
import file_io
import calc

#===========================================================================
if __name__ == "__main__":
    # set file path -----------------------------------------------------
    # prefix = "2024-03-10-05-01-22_UMBRA-04"
    # ifile_path = f"D:/99_working/SRC/radiometric_calibration/DATA/INPUT/{prefix}/"
    # ifile_name = f"{prefix}_SICD.nitf"
    # ijson_name = f"{prefix}_METADATA.json"
    
    prefix = "2025-04-07-14-50-56_UMBRA-05"
    ifile_path = f"D:/99_working/SRC/radiometric_calibration/DATA/INPUT/{prefix}/"
    ifile_name = f"{prefix}_SICD_MM.nitf"
    ijson_name = f"{prefix}.stac.v2.json"
    
    input_file = ifile_path + ifile_name
    json_file  = ifile_path + ijson_name

    ofile_path = "D:/99_working/SRC/radiometric_calibration/DATA/OUTPUT/"
    ofile_name = f"{prefix}_sigma0_db.tif"
    output_file = ofile_path + ofile_name
    
    # read UMBRA SLC data -----------------------------------------------
    print(f"[main]: Read UMBRA SLC data.")
    slc_data, meta_data = file_io.read_umbra_slc(input_file)
        
    # radiometric calibration -------------------------------------------
    print(f"[main]: Start Radiometric Calibration.")
    stack_data = calc.calculate_sigma0(slc_data, meta_data)

    # write data and image ----------------------------------------------
    print(f"[main]: Write Sigma nought.(dB Scale)")
    file_io.plot_sigma0(stack_data[1], ofile_path, prefix)
    file_io.write_geotiff(json_file, output_file, stack_data[1:2])
    
    print(f"[main]: Complete")
