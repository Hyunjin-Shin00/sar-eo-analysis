from snappy import ProductIO

# -------------------------------------------------------------
# 1) Sentinel-1 SLC ZIP 파일 경로 (네가 준 그대로)
# -------------------------------------------------------------
product_path = r"<DATA_ROOT>\07_disaster\landslide\Gyeongju\S1A_IW_SLC__1SDV_20221214T092327_20221214T092357_046326_058C5C_47B8.zip"

print("Reading product...")
product = ProductIO.readProduct(product_path)
if product is None:
    raise RuntimeError("Product read failed. Check product_path.")

md_root = product.getMetadataRoot()

# -------------------------------------------------------------
# 2) 메타데이터 트리 전체에서 heading 값 찾기
#    (platformHeading, platform_heading, heading 등 이름 모두 탐색)
# -------------------------------------------------------------
def find_platform_heading(elem):
    # 1) 현재 element의 attribute들 검사
    for attr_name in elem.getAttributeNames():
        name_lower = attr_name.lower()
        if ("platformheading" in name_lower) or ("platform_heading" in name_lower):
            val = elem.getAttributeString(attr_name)
            print(f"Found heading attribute: {attr_name} = {val}")
            return float(val)
        if name_lower == "heading":
            val = elem.getAttributeString(attr_name)
            print(f"Found heading attribute: {attr_name} = {val}")
            return float(val)

    # 2) 자식 element 재귀 탐색
    for child_name in elem.getElementNames():
        child = elem.getElement(child_name)
        result = find_platform_heading(child)
        if result is not None:
            return result

    return None

heading = find_platform_heading(md_root)

print("\n===== Heading angle (α) =====")
if heading is not None:
    print(f"platform heading : {heading:.4f} deg")
else:
    print("⚠ platform heading not found in metadata tree.")

# -------------------------------------------------------------
# 3) IW2_incident_angle tie-point grid에서 incidence angle(θ) 구하기
# -------------------------------------------------------------
tpg_names = list(product.getTiePointGridNames())
print("\nTie-Point Grids in product:")
for name in tpg_names:
    print("  -", name)

iw2_name = None
for name in tpg_names:
    if name.lower() == "iw2_incident_angle":
        iw2_name = name
        break

if iw2_name is None:
    raise RuntimeError("IW2_incident_angle tie-point grid not found!")

tpg = product.getTiePointGrid(iw2_name)

w = tpg.getRasterWidth()
h = tpg.getRasterHeight()

# 중앙 라인에서 near / center / far 값 읽기
y = h // 2
x_near = 0
x_center = w // 2
x_far = w - 1

theta_near = tpg.getPixelDouble(x_near, y)
theta_center = tpg.getPixelDouble(x_center, y)
theta_far = tpg.getPixelDouble(x_far, y)

print("\n===== IW2 incidence angle (θ) =====")
print(f"Near   (x={x_near:3d}, y={y:3d}) : {theta_near:.4f} deg")
print(f"Center (x={x_center:3d}, y={y:3d}) : {theta_center:.4f} deg")
print(f"Far    (x={x_far:3d}, y={y:3d}) : {theta_far:.4f} deg")

product.dispose()
print("\nDone.")
