import streamlit as st
import pandas as pd
import requests
import re
import xml.etree.ElementTree as ET

# 1. 페이지 기본 설정
st.set_page_config(page_title="한국주식 CANSLIM 퀀트 스캐너 (24/7 안정 버전)", layout="wide")
st.title("📊 나만의 24/7 한국주식 CANSLIM 스캐너")
st.caption("네이버 금융 데이터 엔진을 사용하여 주말, 공휴일, 서버 점검 시간에도 제한 없이 24시간 작동합니다.")

# 2. 사이드바 제어 패널
st.sidebar.header("🎛️ 스크리닝 조건 설정")

# 비밀번호 검증 (유저 커스텀 '123' 적용)
password = st.sidebar.text_input("🔑 접속 비밀번호 입력", type="password")

if password != "123":
    st.warning("사이드바에서 정확한 비밀번호를 입력해야 스캐너가 가동됩니다.")
    st.stop()

# 퀀트 필터 조건 슬라이더
min_value = st.sidebar.slider("최소 거래대금 (억원)", min_value=10, max_value=500, value=50, step=10)
high_margin = st.sidebar.slider("52주 최고가 대비 마진 (%)", min_value=0, max_value=30, value=15, step=1)
vol_multiplier = st.sidebar.slider("20일 평균 대비 오늘 거래량 배수", min_value=1.0, max_value=5.0, value=1.5, step=0.1)
eps_required = st.sidebar.checkbox("당기순이익 흑자 기업만 보기 (PER 존재 기업)", value=True)

# [엔진 1] 네이버 금융 시가총액 상위 종목 마켓 데이터 동기화 (코스피/코스닥 각 상위 250종목, 총 500종목 선별)
@st.cache_data(ttl=21600) # 6시간 동안 데이터 캐싱
def fetch_naver_universe():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    all_stocks = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_pages = 10
    current_page_idx = 0
    
    # sosok=0 (코스피), sosok=1 (코스닥)
    for sosok in [0, 1]:
        for page in range(1, 6):
            current_page_idx += 1
            status_text.text(f"📡 네이버 금융 시장 데이터 동기화 중... ({current_page_idx}/{total_pages} 페이지)")
            progress_bar.progress(current_page_idx / total_pages)
            
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok={sosok}&page={page}"
            try:
                res = requests.get(url, headers=headers, timeout=10)
                # 정규식(Regex)을 이용해 깔끔하게 6자리 종목 코드만 추출
                tickers = re.findall(r'/item/main\.naver\?code=(\d{6})', res.text)
                
                # Pandas로 HTML 테이블 데이터 파싱
                dfs = pd.read_html(res.text, encoding='euc-kr')
                df = dfs[1]
                df = df[df['종목명'].notna()].reset_index(drop=True)
                
                if len(tickers) == len(df):
                    df['티커'] = tickers
                    all_stocks.append(df)
            except Exception:
                continue
                
    progress_bar.empty()
    status_text.empty()
    
    if not all_stocks:
        return pd.DataFrame()
        
    combined_df = pd.concat(all_stocks, ignore_index=True)
    
    # 숫자형 데이터 정제 (, 제거)
    combined_df['현재가'] = pd.to_numeric(combined_df['현재가'].astype(str).str.replace(',', ''), errors='coerce')
    combined_df['거래량'] = pd.to_numeric(combined_df['거래량'].astype(str).str.replace(',', ''), errors='coerce')
    
    # 당일 거래대금 대략적 연산 (현재가 * 거래량) -> 억원 단위 변환
    combined_df['실시간_거래대금_억원'] = (combined_df['현재가'] * combined_df['거래량']) / 100_000_000
    return combined_df

# [엔진 2] 네이버 차트 서버에서 260일(1년) 시세 정보 로드 및 CANSLIM 지표 계산
@st.cache_data(ttl=21600)
def fetch_historical_metrics(universe_df):
    # 속도 극대화를 위한 초강력 필터링: 거래대금 최소 기준(10억원) 미만 종목은 아예 조회 대상에서 제외하여 시간 대폭 단축
    base_df = universe_df[universe_df['실시간_거래대금_억원'] >= 10.0].copy()
    
    final_rows = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total_items = len(base_df)
    
    for i, row in enumerate(base_df.itertuples()):
        status_text.text(f"🚀 52주 신고가 및 거래량 퀀트 연산 중... ({i+1}/{total_items} 종목)")
        progress_bar.progress((i + 1) / total_items)
        
        ticker = row.티커
        # 주말에도 무조건 응답하는 네이버 금융 차트용 XML 엔드포인트 활용
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=260&requestType=0"
        
        try:
            res = requests.get(url, timeout=5)
            root = ET.fromstring(res.text)
            items = root.findall('.//item')
            
            if not items:
                continue
                
            high_prices = []
            volumes = []
            
            for item in items:
                data_str = item.get('data')
                # 데이터 포맷: "날짜|시가|고가|저가|종가|거래량"
                parts = data_str.split('|')
                if len(parts) >= 6:
                    high_prices.append(int(parts[2]))
                    volumes.append(int(parts[5]))
                    
            if not high_prices:
                continue
                
            high_52w = max(high_prices)
            avg_vol_20d = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes) / len(volumes)
            
            close_today = int(parts[4])
            vol_today = int(parts[5])
            
            dist_to_high = ((high_52w - close_today) / high_52w) * 100
            vol_ratio = vol_today / avg_vol_20d if avg_vol_20d > 0 else 0
            
            # PER 값을 이용한 실시간 흑자 여부 판별 (PER가 마이너스나 결측치('-')가 아니면 흑자)
            per_val = str(row.PER).strip().replace(',', '')
            is_profitable = False
            if per_val != 'nan' and per_val != '-' and float(per_val) > 0:
                is_profitable = True
            
            calc_turnover = (close_today * vol_today) / 100_000_000
            
            final_rows.append({
                '티커': ticker,
                '종목名': row.종목명,
                '현재가(원)': close_today,
                '52주 최고가': high_52w,
                '최고가 대비 하락률(%)': round(dist_to_high, 2),
                '오늘 거래량': vol_today,
                '20일 평균 거래량': round(avg_vol_20d, 1),
                '거래량 급증 배수': round(vol_ratio, 2),
                '거래대금(억원)': round(calc_turnover, 1),
                'PER': row.PER,
                '흑자여부': is_profitable
            })
        except Exception:
            continue
            
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_rows)

# -------------------------------------
# 마켓 스크리닝 메인 실행 제어부
# -------------------------------------
universe = fetch_naver_universe()

if not universe.empty:
    metrics_df = fetch_historical_metrics(universe)
    
    if not metrics_df.empty:
        # 슬라이더 동적 연동 필터링 (캐시 밖에서 연산하므로 슬라이더 움직일 때 렉이 전혀 없습니다)
        cond1 = metrics_df['거래대금(억원)'] >= min_value
        cond2 = metrics_df['최고가 대비 하락률(%)'] <= high_margin
        cond3 = metrics_df['거래량 급증 배수'] >= vol_multiplier
        cond4 = metrics_df['흑자여부'] if eps_required else True
        
        final_df = metrics_df[cond1 & cond2 & cond3 & cond4].reset_index(drop=True)
        
        if '흑자여부' in final_df.columns:
            final_df = final_df.drop(columns=['흑자여부'])
            
        st.subheader(f"🔍 조건 만족 종목 (총 {len(final_df)}개 포착)")
        if not final_df.empty:
            final_df = final_df.sort_values(by='최고가 대비 하락률(%)', ascending=True)
            st.dataframe(final_df, use_container_width=True, hide_index=True)
        else:
            st.info("조건을 만족하는 종목이 없습니다. 사이드바의 필터 조건을 조금 더 완화해보세요.")
    else:
        st.error("시세 종목 지표 분석 결과를 도출하지 못했습니다.")
else:
    st.error("네이버 금융 서버 연결에 실패했습니다. 네트워크 상태를 확인하세요.")
