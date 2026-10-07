import pandas as pd, numpy as np, io

# ── 1. 로드 (cp949, 깨진 바이트/줄바꿈 견고 처리) ──────────────
def load(path, term='\n'):
    with open(path, 'rb') as f:
        txt = f.read().decode('cp949', errors='replace')
    if term != '\n':
        txt = txt.replace(term, '\n')          # 지층 파일은 \r 줄바꿈 → 정규화
    return pd.read_csv(io.StringIO(txt), engine='python', on_bad_lines='warn')

bh  = load('국토교통부_지반정보_시추공_20200831.csv')          # 시추공 (1:1)
st  = load('국토교통부_지반정보_지층정보_20230831.csv', term='\r')  # 지층 (1:N)
spt = load('국토교통부_지반정보_표준관입시험정보.csv')          # SPT  (1:N)

# 컬럼명/키 정리
for df in (bh, st, spt):
    df.columns = [c.strip() for c in df.columns]
    df['시추공코드'] = df['시추공코드'].astype(str).str.strip()

# ── 2. 3개 파일 공통 시추공만 추출 (교집합) ──────────────────
common = set(bh['시추공코드']) & set(st['시추공코드']) & set(spt['시추공코드'])
bh  = bh[bh['시추공코드'].isin(common)].copy()
st  = st[st['시추공코드'].isin(common)].copy()
spt = spt[spt['시추공코드'].isin(common)].copy()

# 심도 숫자화
spt['시험심도']   = pd.to_numeric(spt['시험심도'], errors='coerce')
st['지층시작심도'] = pd.to_numeric(st['지층시작심도'], errors='coerce')
st['지층종료심도'] = pd.to_numeric(st['지층종료심도'], errors='coerce')

# ── 3. 시추공 메타 (시추공코드 1:1) ──────────────────────────
bh_meta = bh.drop_duplicates('시추공코드', keep='first')

# ── 4. 지층 구간 매칭 (SPT 시험심도 → [시작, 종료) 포함 지층) ──
st_cols = ['지층시작심도','지층종료심도','지층두께','토목용지층명',
           '학술용지층명USCS','학술용지층코드','학술용지층명','토질색상','지층코드']
st_use = st[['시추공코드'] + st_cols].dropna(subset=['지층시작심도','지층종료심도'])

spt = spt.reset_index(drop=True)
spt['_sid'] = np.arange(len(spt))                       # SPT 행 식별자

# 시추공코드로만 결합 후 구간 조건 필터 (벡터화)
m = spt[['_sid','시추공코드','시험심도']].merge(st_use, on='시추공코드', how='left')
d = m['시험심도']
inside = (m['지층시작심도'] <= d) & (d < m['지층종료심도'])           # start <= d < end
edge   = (m['지층시작심도'] <= d) & (d <= m['지층종료심도'])           # 종료심도 경계 보정

m_in = m[inside]
m_edge = m[(~m['_sid'].isin(set(m_in['_sid']))) & edge]              # 미매칭만 경계조건 재시도
m_all = (pd.concat([m_in, m_edge], ignore_index=True)
           .sort_values(['_sid','지층시작심도'])
           .drop_duplicates('_sid', keep='first'))                  # 행당 첫 매칭

layer = m_all.set_index('_sid')[st_cols]
spt_st = spt.merge(layer, left_on='_sid', right_index=True, how='left')

# ── 5. 시추공 메타 결합 + 컬럼 정렬 + 저장 ───────────────────
out = spt_st.drop(columns=['_sid']).merge(bh_meta, on='시추공코드', how='left')

col_order = (['시추공코드','프로젝트코드','프로젝트명',
              '고도','시추심도','지하수위','시추방법','시추공종류','X좌표','Y좌표',
              '시험심도','관입깊이','타격회수'] + st_cols)
col_order = [c for c in col_order if c in out.columns]
out = out[col_order + [c for c in out.columns if c not in col_order]]

out.to_csv('지반정보_통합_SPT단위.csv', index=False, encoding='utf-8-sig')

print(f'행수 {len(out):,} / 고유 시추공 {out["시추공코드"].nunique():,} / '
      f'지층 매칭률 {out["학술용지층명USCS"].notna().mean()*100:.1f}%')
# → 행수 920,047 / 고유 시추공 92,307 / 지층 매칭률 99.6%