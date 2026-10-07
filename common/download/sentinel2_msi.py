
import time
start_time = time.time()

import os
import pandas as pd
import requests
from tqdm import tqdm

from pprint import pprint

import zipfile


os.system('date')


###############################################################
#my account @ [browser.dataspace.copernicus.eu]
ID = '***REMOVED***@kangwon.ac.kr'
PW = 'Hyunjin1006!'
###############################################################



Nrepeat = 5


for iMain in range(Nrepeat):
    print('\n\n\n === %dth/%d repeat try! === \n\n\n'%(iMain+1,Nrepeat))

    #for mainYear in ['2018','2019','2020','2021','2022','2023']:
    #for mainYear in reversed(['2019','2020','2021','2022']):
    #for mainYear in ['2022']:
    #for mainYear in ['2016','2017','2018','2019','2020','2021','2022','2023','2024']:
    #for mainYear in reversed(['2016','2017','2018','2024']):
    #for mainYear in reversed(['2019','2020','2021','2022']):
    #for mainYear in ['2016','2017','2018','2024']:
    #for mainYear in ['2019','2020','2021','2022','2023']:
    for mainYear in reversed(['2018','2019','2020','2021','2022','2023','2024']):

        try:

            YEAR = mainYear


            N_newDownloads = 0
            N_reDownloads = 0


            def area_of_interest(min_lon, max_lon, min_lat, max_lat):
                """
                Format a string with the given minimum and maximum longitudes and latitudes
                to create the bounding polygon around a source.
                """
                polygon = (
                    "POLYGON(("
                    f"{min_lon} {min_lat},"  # Bottom-Left
                    f"{min_lon} {max_lat},"  # Top-Left
                    f"{max_lon} {max_lat},"  # Top-Right
                    f"{max_lon} {min_lat},"  # Bottom-Right
                    f"{min_lon} {min_lat}))"  # Bottom-Left
                )
                return polygon


            def list_files(
                west_lon,
                east_lon,
                south_lat,
                north_lat,
                start_date,
                end_date,
                productType,
                orbit='-',
                only_latest=False,
            ):
                """\
                Create list of data file names based on the input.
                Return the file list, the size of each file and the product details.
                """
                ids = []
                filenames = []

                # format some of the parameters
                orbit = None if orbit == "-" else orbit

                footprint = area_of_interest(west_lon, east_lon, south_lat, north_lat)

                # Query per day as the number of returns per query is limited to 20
                # (LEO: 14-15 orbits per day)
                for date in pd.date_range(start_date, end_date):
                    start_date = date.strftime("%Y-%m-%dT00:00:00Z")
                    end_date = date.strftime("%Y-%m-%dT23:59:59Z")

                    # define components of the query
                    url_init = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products?$filter=Collection/Name eq 'SENTINEL-2'"
                    proc_ty = (
                        f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/OData.CSC.StringAttribute/Value eq '{productType}')"
                        if productType
                        else productType
                    )
                    orb_nr = (
                        f"Attributes/OData.CSC.IntegerAttribute/any(att:att/Name eq 'orbitNumber' and att/OData.CSC.IntegerAttribute/Value eq '{orbit}')"
                        if orbit
                        else orbit
                    )
                    bbox = (
                        f"OData.CSC.Intersects(area=geography'SRID=4326;{footprint}')"
                        if footprint
                        else footprint
                    )
                    st_date = f"ContentDate/Start ge {start_date}" if start_date else start_date
                    end_date = f"ContentDate/Start le {end_date}" if end_date else end_date
                    query = " and ".join(
                        filter(
                            None,
                            [
                                url_init,
                                proc_ty,
                                orb_nr,
                                bbox,
                                st_date,
                                end_date,
                            ],
                        )
                    )

                    #print('\nquery=',query)
                    try:
                        # Access the API and create query
                        products = requests.get(query).json()
                    except:
                        raise ConnectionError("Error connecting to the server")

                    #print('\nproducts=',products)
                    if 'value' in products:
                        ids_day = [v['Id'] for v in products['value']]
                        fns_day = [v['Name'] for v in products['value']]

                        ids.extend(ids_day)
                        filenames.extend(fns_day)
                    else:
                        print(f'No results for {date.strftime("%Y-%m-%d")}.')

                return ids, filenames


            class Download:
                def __init__(self, path, username, password):
                    self.save_path = path
                    self.username = username
                    self.password = password
                    self.keycloak_token = None

                def get_keycloak(self) -> str:
                    data = {
                        "client_id": "cdse-public",
                        "username": self.username,
                        "password": self.password,
                        "grant_type": "password",
                    }
                    try:
                        r = requests.post(
                            "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
                            data=data,
                        )
                        r.raise_for_status()
                    except Exception as e:
                        raise Exception(
                            f"Keycloak token creation failed. Response from the server was: {r.json()}"
                        )
                    return r.json()["access_token"]

                def download_files(self, ids, filenames):
                    global N_newDownloads
                    global N_reDownloads


                    # open session (using exisiting token if available)
                    if self.keycloak_token is None:
                        self.keycloak_token = self.get_keycloak()

                    session = requests.Session()
                    session.headers.update({"Authorization": f"Bearer {self.keycloak_token}"})

                    # iterrat of filenames

                    for file_id, file_name in zip(ids, filenames):

                        try:
                            print(f"Querying {file_name}")
                            url = f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({file_id})/$value"
                            response = session.get(url, allow_redirects=False, stream=True)

                            if os.path.exists(os.path.join(self.save_path, file_name+'.zip')):
                                print(' This file already exists:')

                                try:
                                    with zipfile.ZipFile(os.path.join(self.save_path, file_name+'.zip'), 'r') as zip_ref:
                                        # Test the zip file integrity
                                        bad_file = zip_ref.testzip()
                                        if bad_file:
                                            print(f" -->> Downloading again! - the zip file is corrupted {bad_file}.")
                                            N_reDownloads += 1
                                        else:
                                            print(f" -->> Skipping downloading! - the zip file {file_name} is complete and uncorrupted.")
                                            continue
                                except zipfile.BadZipFile:
                                    print(f" -->>  Downloading again! - the zip file {file_name} is invalid or corrupted.")
                                    N_reDownloads += 1

                            else:
                                N_newDownloads += 1


                            while response.status_code in (301, 302, 303, 307, 401):
                                url = response.headers["Location"]
                                response = session.get(url, allow_redirects=False, stream=True)

                                if response.status_code == 401:
                                    self.keycloak_token = self.get_keycloak()
                                    session.headers.update(
                                        {"Authorization": f"Bearer {self.keycloak_token}"}
                                    )

                            if response.status_code not in range(200, 299):
                                raise Exception(
                                    f"Unsuccessful server response. Status code: {response.status_code}"
                                )

                            folder_name = (
                                response.headers.get("Content-Disposition")
                                .split("filename=")[-1]
                                .strip('"')
                            )
                            folderpath = os.path.join(self.save_path, folder_name)
                            folderpath = folderpath.replace("zip", "SAFE.zip")

                            with open(folderpath, "wb") as file:
                                file_size = int(response.headers.get("Content-Length", 0))
                                progress = tqdm(
                                    total=file_size,
                                    unit="iB",
                                    unit_scale=True,
                                    desc=f"Downloading {folderpath}",
                                    miniters=1,
                                )
                                for data in response.iter_content(1024):
                                    file.write(data)
                                    progress.update(len(data))
                                progress.close()

                        except Exception as e:
                            print(f"Error downloading file with id {file_name}: {str(e)}")








            #######################
            ### -- Germany -- ###
            #######################


            ###############################################################
            #-<Hamburg>-
            tileId = 'T32UNE'
            center_lat = 53.51278
            center_lon = 10.03806
            ###############################################################






            # crude margin distance to cover roi
            lat_margin = 0.05  # in degree
            lon_margin = 0.05  # in degree


            west_lon = center_lon - lon_margin
            east_lon = center_lon + lon_margin
            south_lat = center_lat - lat_margin
            north_lat = center_lat + lat_margin



            ###############################################################
            #-Level-1 or Level-2?
            productType = 'S2MSI1C'  #'S2MSI1C' 'S2MSI2A'

            ###############################################################
            #for possible quota, lets split into 1st half and 2nd half of a year
            start_date = YEAR+'-01-01'
            end_date = YEAR+'-12-31'



            #data_path_raw = os.path.join('data', productType, tileId, start_date[:4])
            data_path_raw = os.path.join('Sentinel-2_MSI', 'L1C', tileId, start_date[:4])
            os.makedirs(data_path_raw, exist_ok=True)
            pprint(data_path_raw)


            itime = time.time()
            ids, filenames = list_files(
                   west_lon, east_lon, south_lat, north_lat,
                   start_date=start_date,
                   end_date=end_date,
                   productType=productType,
            )
            etime = time.time() - itime
            print('\n list file acquiring Time (HH:MM:SS) = ', time.strftime("%H:%M:%S",time.gmtime(etime)), '\n')




            #only for the tile name
            if tileId is not None:
                final_ids = []
                final_filenames = []

                for i,f in zip(ids, filenames):
                    #print('id, filename=',i,f)
                    if tileId in f:
                        #print(' *** => ', tileId,' is in ',f)
                        final_ids.append(i)
                        final_filenames.append(f)
            else:
                final_ids = ids
                final_filenames = filenames



            print('\n',len(final_ids), len(final_filenames),'\n')
            #pprint(final_ids)
            pprint(final_filenames)
            print('\n')
            #stop



            downloader = Download(data_path_raw, ID, PW)
            downloader.download_files(final_ids, final_filenames)




            print('\n<Process ends>\nn(all list files) = ',len(final_filenames))
            print('n(new-Download tries) = ',N_newDownloads)
            print('n(re-Download tires) =  ',N_reDownloads)


            seconds = time.time() - start_time
            print('\nTime elapsed(HH:MM:SS) = ', time.strftime("%H:%M:%S",time.gmtime(seconds)), '\n')

            os.system('date')



        except Exception as e:
            print(' **** this time -  error occured = ', e)


print('\n*total Time elapsed(hrs) = ', (time.time() - start_time)/3600., '\n')

print('\nEnd of Run\n')


stop



