import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from pykrx import stock

# 1. 페이지 기본 설정
st.set_page_config(page_title="한국주식 CANSLIM 퀀트 스캐너", layout="wide")
st.title("📊 나만의 한국주식 CANSLIM 스캐너")
st.caption("CANSLIM 조건(신고가 근접, 거래량 급증, 흑자 기업)을 기준으로 주도주를 포착합니다.")

# 2. 최신 거래일 자동 찾기 함수 (주말/공휴일 방지)
@st.cache_data(ttl=3600)
def get_latest_trading_date():
    target_date = datetime.now()
    for _ in range(7):
        date_str = target_date.strftime("%Y%m%d")
        df = stock.get_market_ohlcv_by_ticker(date_str, market="ALL")
        if not df.empty:
            return target_date, date_str
        target_date -= timedelta(days=1)
    return datetime.now(), datetime.now().strftime("%Y%m%d")

latest_date, latest_date_str = get_latest_trading_date()
st.info(f"📅 현재 반영된 최신 데이터 기준일: **{latest_date.strftime('%Y-%m-%d')}**")

# 3. 사이드바 제어 패널 (나만의 조건 조절)
st.sidebar.header("🎛️ 스크리닝 조건 설정")

min_value = st.sidebar.slider("최소 거래대금 (억원)", min_value=10, max_value=500, value=50, step=10)
high_margin = st.sidebar.slider("52주 최고가 대비 마진 (%)", min_value=0, max_value=30, value=15, step=1)
vol_multiplier = st.sidebar.slider("20일 평균 대비 오늘 거래량 배수", min_value=1.0, max_value=5.0, value=1.5, step=0.1)
eps_required = st.sidebar.checkbox("당기순이익 흑자 기업만 보기 (EPS > 0)", value=True)

# 비밀번호 잠금장치 (간단한 프라이빗 설정)
password = st.sidebar.text_input("🔑 접속 비밀번호 입력", type="password")

if password != "내비밀번호123":  # 원하시는 비밀번호로 변경하세요
    st.warning("사이드바에서 정확한 비밀번호를 입력해야 스캐너가 가동됩니다.")
    st.stop()

# 4. 데이터 로드 및 연산 수행
@st.cache_data(ttl=21600) # 6시간 동안 데이터 캐싱 (속도 업그레이드)
def fetch_canslim_universe(date_str, min_val_krw):
    # 당일 시세 정보
    df_today = stock.get_market_ohlcv_by_ticker(date_str, market="ALL")
    # 종목명 딕셔너리 구축
    ticker_names = {ticker: stock.get_market_ticker_name(ticker) for ticker in df_today.index}
    
    # 1차 필터링: 거래대금 기준 만족하는 종목만 선별 (잡주 제거로 속도 확보)
    df_filtered = df_today[df_today['거래대금'] >= min_val_krw].copy()
    tickers = df_filtered.index.tolist()
    
    # 기본적 분석 데이터 (EPS, PER 등)
    df_fund = stock.get_market_fundamental_by_ticker(date_str, market="ALL")
    
    # 52주 데이터 조회를 위한 날짜 계산
    end_dt = datetime.strptime(date_str, "%Y%m%d")
    start_dt = end_dt - timedelta(days=365)
    start_date_str = start_dt.strftime("%Y%m%d")
    
    final_rows = []
    
    # 루프를 돌며 개별 종목의 52주 최고가 및 20일 평균 거래량 계산
    # 종목수가 조절되므로 연산 속도가 빠릅니다.
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, ticker in enumerate(tickers):
        status_text.text(f"🚀 퀀트 분석 진행 중... ({i+1}/{len(tickers)})")
        progress_bar.progress((i + 1) / len(tickers))
        
        try:
            df_hist = stock.get_market_ohlcv_by_date(start_date_str, date_str, ticker)
            if df_hist.empty:
                continue
                
            high_52w = df_hist['고가'].max()
            avg_vol_20d = df_hist['거래량'].iloc[-20:].mean() if len(df_hist) >= 20 else df_hist['거래량'].mean()
            
            close = df_today.loc[ticker, '종가']
            vol = df_today.loc[ticker, '거래량']
            val = df_today.loc[ticker, '거래대금']
            
            dist_to_high = ((high_52w - close) / high_52w) * 100
            vol_ratio = vol / avg_vol_20d if avg_vol_20d > 0 else 0
            eps = df_fund.loc[ticker, 'EPS'] if ticker in df_fund.index else 0
            per = df_fund.loc[ticker, 'PER'] if ticker in df_fund.index else 0
            
            final_rows.append({
                '티커': ticker,
                '종목명': ticker_names.get(ticker, ''),
                '현재가': int(close),
                '52주 최고가': int(high_52w),
                '최고가 대비 하락률(%)': round(dist_to_high, 2),
                '오늘 거래량': int(vol),
                '20일 평균 거래량': round(avg_vol_20d, 1),
                '거래량 급증 배수': round(vol_ratio, 2),
                '거래대금(억원)': round(val / 100_000_000, 1),
                'EPS': int(eps),
                'PER': round(per, 2)
            })
        except:
            continue
            
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_rows)

# 최소 거래대금 원 단위 변환 (억 -> 원)
min_val_krw = min_value * 100_000_000
raw_results = fetch_canslim_universe(latest_date_str, min_val_krw)

# 5. 유저가 설정한 사이드바 조건에 맞춰 최종 필터링
if not raw_results.empty:
    cond1 = raw_results['최고가 대비 하락률(%)'] <= high_margin
    cond2 = raw_results['거래량 급증 배수'] >= vol_multiplier
    cond3 = raw_results['EPS'] > 0 if eps_required else True
    
    final_df = raw_results[cond1 & cond2 & cond3].reset_index(drop=True)
    
    # 결과 화면 출력
    st.subheader(f"🔍 조건 만족 종목 (총 {len(final_df)}개 포착)")
    if not final_df.empty:
        # 가시성을 위해 소팅 제공 (최고가에 가장 가까운 순)
        final_df = final_df.sort_values(by='최고가 대비 하락률(%)', ascending=True)
        st.dataframe(final_df, use_container_width=True, hide_index=True)
    else:
        st.info("조건을 만족하는 종목이 없습니다. 사이드바의 필터 조건을 완화해보세요.")
else:
    st.error("데이터를 불러오지 못했습니다.")