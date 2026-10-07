

#refer to https://m2m.cr.usgs.gov/api/docs/json/
#from https://code.usgs.gov/eros-user-services/machine_to_machine/m2m_landsat_9_search_download


import json
from getpass import getpass
import requests
import sys
import time
start_time = time.time()
from pprint import pprint
from tqdm import tqdm
import cgi
import os
import pandas as pd
import geopandas as gpd
import warnings

warnings.filterwarnings("ignore")
os.system('date')



# Send http request
def sendRequest(url, data, apiKey = None, exitIfNoResponse = True):
    """
    Send a request to an M2M endpoint and returns the parsed JSON response.

    Parameters:
    endpoint_url (str): The URL of the M2M endpoint
    payload (dict): The payload to be sent with the request

    Returns:
    dict: Parsed JSON response
    """

    json_data = json.dumps(data)

    if apiKey == None:
        response = requests.post(url, json_data)
    else:
        headers = {'X-Auth-Token': apiKey}
        response = requests.post(url, json_data, headers = headers)

    try:
      httpStatusCode = response.status_code
      if response == None:
          print("No output from service")
          if exitIfNoResponse: sys.exit()
          else: return False
      output = json.loads(response.text)
      if output['errorCode'] != None:
          print(output['errorCode'], "- ", output['errorMessage'])
          if exitIfNoResponse: sys.exit()
          else: return False
      if  httpStatusCode == 404:
          print("404 Not Found")
          if exitIfNoResponse: sys.exit()
          else: return False
      elif httpStatusCode == 401:
          print("401 Unauthorized")
          if exitIfNoResponse: sys.exit()
          else: return False
      elif httpStatusCode == 400:
          print("Error Code", httpStatusCode)
          if exitIfNoResponse: sys.exit()
          else: return False
    except Exception as e:
          response.close()
          print(e)
          if exitIfNoResponse: sys.exit()
          else: return False
    response.close()

    return output['data']



def downloadfiles(downloadIds):
   downloadIds.append(download['downloadId'])
   print("    DOWNLOADING: " + download['url'])
   downloadResponse = requests.get(download['url'], stream=True, timeout=1200)

   # parse the filename from the Content-Disposition header
   content_disposition = cgi.parse_header(downloadResponse.headers['Content-Disposition'])[1]
   filename = os.path.basename(content_disposition['filename'])
   filepath = os.path.join(save_folder, filename)

   # write the file to the destination directory
   with open(filepath, 'wb') as f:
       for data in downloadResponse.iter_content(chunk_size=8192):
           f.write(data)





serviceUrl = "https://m2m.cr.usgs.gov/api/api/json/stable/"


def login(username, token):
    print("Logging in...\n")
    login_payload = {'username': username, 'token': token}

    try:
        apiKey = sendRequest(serviceUrl + "login-token", login_payload)
        print("API Key obtained: " + apiKey + "\n")
        return apiKey
    except Exception as e:
        print(f"API login failed: {e}")
        return None



def logout():
    global apiKey

    try:
        if sendRequest(serviceUrl + "logout", None, apiKey) == None:
            print("\n\nLogged out successfully.\n")
        else:
            print("\n\nLogout Failed\n")

    except Exception as e:
        print(f"Logout failed: {e}")




CHECK_INTERVAL = 3600 # checking every 1 hr (should be < 2hrs)
last_api_check_time = 0


def check_and_refresh_api_key(username, token):
    global apiKey, last_api_check_time

    timeinterval = time.time() - last_api_check_time
    if timeinterval < CHECK_INTERVAL:
        print(f'\tNo need to check API Key status ({timeinterval/60:.1f} mins < 1hr since last use)')
        return

    print("Checking API Key status...")

    test_url = serviceUrl + "dataset-search"  # simple test to check apikey status

    try:
        response = sendRequest(test_url, {}, apiKey)

        if isinstance(response, list) and any(
            "AUTH_EXPIRED" in item.values() or "AUTH_UNAUTHORIZED" in item.values()
            for item in response if isinstance(item, dict)
        ):
            print("API Key expired. Logging out and re-authenticating...\n")

            logout()
            apiKey = login(username, token)

            if not apiKey:
                print("Failed to refresh API key. Exiting.")
                exit(1)
        else:
            print("API Key is still valid.\n")

        last_api_check_time = time.time()

    except Exception as e:
        print(f"API Key validation error: {e}. Trying to re-authenticate...\n")

        logout()
        apiKey = login(username, token)

        last_api_check_time = time.time()






##################  ID PW  #################
username = ""  # ERS username (ers.cr.usgs.gov)
token = ""  # your M2M API token with approved data access
############################################




#-initial API key login
apiKey = login(username, token)




############ ROI BBox in degree  ###########
### -Hamburg in Germany ###
Smelter = 'Hamburg'
center_lat = 53.51278
center_lon = 10.03806
############################################






# crude margin distance to cover roi
lat_margin = 0.05  # in degree
lon_margin = 0.05  # in degree


min_lat = center_lat - lat_margin
max_lat = center_lat + lat_margin
min_lon = center_lon - lon_margin
max_lon = center_lon + lon_margin


spatialFilter = {'filterType' : 'mbr',
                  'lowerLeft' : {'latitude'  : min_lat,\
                                 'longitude' : min_lon},
                 'upperRight' : {'latitude'  : max_lat,\
                                 'longitude' : max_lon}}





#-setting for file download retry when failed
retries = 5
delay = 10



# repeat whole processes to make sure all files complete
NrepeatAll = 5


for iMain in range(NrepeatAll):
    print('\n\n\n === %dth/%d repeat try of whole run! === \n\n\n'%(iMain+1,NrepeatAll))


    ############  YEAR  ###########
    #for Year in ['2016','2017','2018','2019','2020','2021','2022','2023','2024']:
    #for Year in reversed(['2016','2017','2018','2019','2020','2021','2022','2023','2024']):
    for Year in reversed(['2018','2019','2020','2021','2022','2023','2024']):
    #for Year in ['2025']:


        try:

            save_folder = f"Landsat-89_OLI/L1/{Smelter}/{Year}"
            print(f'save_folder={save_folder}\n')
            os.makedirs(save_folder, exist_ok=True)



            n_img_per_yr = 0
            ## n=69, n=67, n=100 (there is file number limit upto 100) split a year into 1st half and 2nd half
            for halfyear in [{'start' : f'{Year}-01-01', 'end' : f'{Year}-06-30'},{'start' : f'{Year}-07-01', 'end' : f'{Year}-12-31'}]:


                print(f'\n\nSmelter={Smelter} year={Year} with {halfyear}')

                temporalFilter = halfyear


                datasearch_payload = {'datasetName': 'Landsat 8-9',
                                  'temporalFilter' : temporalFilter}

                datasearch_result = sendRequest(serviceUrl + "dataset-search", datasearch_payload, apiKey)

                print(pd.json_normalize(datasearch_result))



                # 0 for Level-1 (landsat_ot_c2_l1)
                # 1 for Level-2 (landsat_ot_c2_l2)
                datasetName = datasearch_result[0]['datasetAlias']
                #print('datasetName =',datasetName)



                search_payload = {
                    'datasetName' : datasetName,
                    'sceneFilter' : {
                        #'metadataFilter' : metadataFilter,
                        'spatialFilter' : spatialFilter,
                        'acquisitionFilter' : temporalFilter,
                        'cloudCoverFilter' : {'min' : 0, 'max' : 100}
                    }
                }

                pprint(search_payload)


                scenes = sendRequest(serviceUrl + "scene-search", search_payload, apiKey)


                #print(pd.json_normalize(scenes['results']))



                sceneIds = []
                for result in scenes['results']:
                    # Add this scene to the list to be downloaded
                    sceneIds.append(result['entityId'])
                    #print(result['entityId'])

                n_img_per_yr += len(sceneIds)

                print(' -> len(sceneIds)=',len(sceneIds))
                #print('sceneIds=',sceneIds)




                total_hits = scenes.get("totalHits", 0)
                print(f"number of total scenes found (<100?) = {total_hits}")
                if total_hits >= 100:
                    print(' XXX number of scenes found = 100 (maximum allowed!!!) \n -> need to split a year into 3 or more periods')
                    stop

                if not scenes['results']:
                    print("no more data to search")
                    stop


                download_payload = {'datasetName' : datasetName,
                                      'entityIds' : sceneIds}

                downloadOptions = sendRequest(serviceUrl + "download-options", download_payload, apiKey)


                #print(pd.json_normalize(downloadOptions))

                #NOTE: The scene list cannot exceed 50,000 items. 



                availableproducts = []
                for product in downloadOptions:
                        # Make sure the product is available for this scene
                        if product['available'] == True and product['downloadSystem'] != 'folder':
                                availableproducts.append({'entityId' : product['entityId'],
                                                         'productId' : product['id']})


                #print(availableproducts)


                requestedDownloadsCount = len(availableproducts)

                # set a label for the download request
                label = "download-sample"
                download_req_payload = {'downloads' : availableproducts,
                                            'label' : label}

                requestResults = sendRequest(serviceUrl + "download-request", download_req_payload, apiKey)
                #print(requestResults)




                if requestResults['preparingDownloads'] != None and len(requestResults['preparingDownloads']) > 0:
                    download_retrieve_payload = {'label' : label}

                    print("Requesting for additional available download urls...")
                    moreDownloadUrls = sendRequest(serviceUrl + "download-retrieve", download_retrieve_payload, apiKey)

                    downloadIds = []


                    print("\nDownloading from available downloads:")
                    for download in moreDownloadUrls['available']:
                        if str(download['downloadId']) in requestResults['newRecords'] or str(download['downloadId']) in requestResults['duplicateProducts']:
                            downloadfiles(downloadIds)


                    print("\nDownloading from requested downloads:")
                    for download in moreDownloadUrls['requested']:
                        if str(download['downloadId']) in requestResults['newRecords'] or str(download['downloadId']) in requestResults['duplicateProducts']:
                            downloadfiles(downloadIds)


                    # Didn't get all of the reuested downloads, call the download-retrieve method again probably after 30 seconds
                    while len(downloadIds) < (requestedDownloadsCount - len(requestResults['failed'])):
                        preparingDownloads = requestedDownloadsCount - len(downloadIds) - len(requestResults['failed'])
                        print("    ", preparingDownloads, " downloads are not available. Waiting for 30 seconds...")
                        time.sleep(30)
                        print("    Trying to retrieve data after waiting for 30 seconds...")
                        moreDownloadUrls = sendRequest(serviceUrl + "download-retrieve", download_retrieve_payload, apiKey)
                        for download in moreDownloadUrls['available']:
                            if download['downloadId'] not in downloadIds and (str(download['downloadId']) in requestResults['newRecords'] or str(download['downloadId']) in requestResults['duplicateProducts']):
                                downloadfiles(downloadIds)


                else:
                    print("\nAll downloads are available to download. Retrieving...\n") # Get all available downloads

                    i = 1   # 1st

                    for download in requestResults['availableDownloads']:

                        #https://landsatlook.usgs.gov/gen-bundle?
                        #https://landsatlook.usgs.gov/gen-browse?
                        if download['url'][33:39] != 'bundle': #-download .tar bundle file only (not other .tif .jpg files)
                            continue


                        #-check whether API key has expired due to inactivity (NOTE: The Machine-to-Machine API key expires after 2 hours of inactivity.)
                        check_and_refresh_api_key(username, token)


                        #https://landsatlook.usgs.gov/gen-bundle?landsat_product_id=LC08_L1TP_090084_20160629_20200906_02_T1
                        #print("Downloading: " + download['url'])
                        #print(f"{i:3d}th Downloading : entityId = " + download['entityId'])
                        print(f"{i:3d}th file Downloading : product_id=" + download['url'][59:59+40])

                        downloadResponse = requests.get(download['url'], stream=True, timeout=1200)

                        # parse the filename from the Content-Disposition header
                        content_disposition = cgi.parse_header(downloadResponse.headers['Content-Disposition'])[1]
                        filename = os.path.basename(content_disposition['filename'])
                        filepath = os.path.join(save_folder, filename)

                        filesize = int(cgi.parse_header(downloadResponse.headers['Content-Length'])[0])

                        if os.path.exists(filepath) and os.path.getsize(filepath) == filesize:
                            print(f'current filesize={os.path.getsize(filepath)}/{filesize}=fullsize')
                            print(f" -> Skipping! (already fully downloaded.): {filepath} \n")
                            i += 1
                            continue


                        for attempt in range(retries):
                            try:
                                # write the file to the destination directory
                                with open(filepath, 'wb') as f:
                                    progress = tqdm(
                                        total=filesize,
                                        unit="iB",
                                        unit_scale=True,
                                        desc=f" --- downloading into {filepath}",
                                        miniters=1,
                                    )
                                    for data in downloadResponse.iter_content(chunk_size=8192):
                                        f.write(data)
                                        progress.update(len(data))
                                    progress.close()

                                print(f" -> Download completed! ({i}/{len(sceneIds)}) = {filename} \n")
                                i+=1
                                break

                            except (requests.exceptions.RequestException, requests.exceptions.ChunkedEncodingError) as E:
                                print(f" xxx download failure!! (retry {attempt+1}/{retries}): {E}")
                                time.sleep(delay)


            print(f"\n\n{Smelter} {Year} : a total of {n_img_per_yr} Landsat images have been downloaded.")

            os.system('du -h '+save_folder)

            seconds = time.time() - start_time
            print('\nTime elapsed(HH:MM:SS) = ', time.strftime("%H:%M:%S",time.gmtime(seconds)), '\n')

            os.system('date')
            print('\n')


        except Exception as e:
            print(' **** this time -  error occured = ', e)




logout()

print('\n*total Time elapsed(hrs) = ', (time.time() - start_time)/3600., '\n')

print('\nEnd of Run\n')


stop


