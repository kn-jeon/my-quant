import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET

# 1. 페이지 기본 설정
st.set_page_config(page_title="한국주식 CANSLIM 주도주 스캐너", layout="wide")
st.title("🚀 나만의 24/7 한국주식 CANSLIM 스캐너")
st.caption("차단 없는 전용 차트 엔진을 활용하여 주말, 공휴일, 서버 점검 시간에도 365일 실시간 작동합니다.")

# 2. 사이드바 제어 패널
st.sidebar.header("🎛️ 스크리닝 조건 설정")

# 비밀번호 검증 (유저 커스텀 '123' 적용)
password = st.sidebar.text_input("🔑 접속 비밀번호 입력", type="password")

if password != "123":
    st.warning("사이드바에서 정확한 비밀번호를 입력해야 스캐너가 가동됩니다.")
    st.stop()

# 퀀트 필터 조건 슬라이더
min_value = st.sidebar.slider("최소 거래대금 (억원)", min_value=10, max_value=500, value=30, step=10)
high_margin = st.sidebar.slider("52주 최고가 대비 마진 (%)", min_value=0, max_value=30, value=15, step=1)
vol_multiplier = st.sidebar.slider("20일 평균 대비 오늘 거래량 배수", min_value=1.0, max_value=5.0, value=1.3, step=0.1)

# [🔑 치트키] 스트림릿 클라우드 IP 차단을 우회하기 위한 대한민국 핵심 주도주/대형주 유니버스 구축
TICKER_DICT = {
    # 반도체 / AI / 장비
    "005930": "삼성전자", "000660": "SK하이닉스", "042700": "한미반도체", "089030": "테크윙", 
    "390870": "이오테크닉스", "058470": "리노공업", "005290": "동진쎄미켐", "067310": "하나마이크론", 
    "240810": "원익IPS", "036930": "주성엔지니어링", "178920": "피에스케이", "323280": "태성",
    # 바이오 / 제약
    "207940": "삼성바이오로직스", "068270": "셀트리온", "196170": "알테오젠", "028300": "HLB",
    "145020": "휴젤", "128940": "한미약품", "000100": "유한양행", "214150": "클래시스", "235980": "메디톡스",
    # 배터리 / 2차전지 / 소재
    "373220": "LG에너지솔루션", "051910": "LG화학", "006400": "삼성SDI", "247540": "에코프로비엠",
    "086520": "에코프로", "066970": "엘앤에프", "003670": "포스코인터내셔널", "005490": "POSCO홀딩스",
    # 전력기기 / 우주항공 / 인프라 중공업 (슈퍼 주도주 섹터)
    "043200": "HD현대일렉트릭", "012450": "한화에어로스페이스", "454910": "두산에너빌리티", "010140": "삼성중공업",
    "009830": "한화솔루션", "000720": "현대건설", "022100": "포스코DX", "003230": "삼양식품", "271560": "오리온",
    # 금융 / 지주사 / 밸류업 호재주
    "105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주", "323410": "카카오뱅크",
    "000810": "삼성화재", "016360": "삼성증권", "006800": "미래에셋증권", "071050": "한국금융지주",
    "138040": "메리츠금융지주", "028260": "삼성물산", "003490": "대한항공", "011200": "HMM",
    # 엔터 / 플랫폼 / 게임 / IT
    "035420": "NAVER", "035720": "카카오", "352820": "하이브", "035900": "JYP Ent.", 
    "041510": "에스엠", "122870": "와이지엔터테인먼트", "259960": "크래프톤", "036570": "엔씨소프트",
    "293490": "카카오게임즈", "253450": "스튜디오드래곤", "066570": "LG전자", "034220": "LG디스플레이"
}

# 3. 데이터 연산 제어부 (서버 점검의 영향을 받지 않는 전용 데이터 파이프라인)
@st.cache_data(ttl=3600)
def scan_canslim_leaders():
    final_rows = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_items = len(TICKER_DICT)
    
    for i, (ticker, name) in enumerate(TICKER_DICT.items()):
        status_text.text(f"🚀 핵심 주도주 퀀트 스캔 중... ({i+1}/{total_items} 종목)")
        progress_bar.progress((i + 1) / total_items)
        
        # 260일(1년) 데이터를 즉시 반환하는 네이버 전용 백엔드 주소 활용
        url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=260&requestType=0"
        
        try:
            res = requests.get(url, timeout=5)
            root = ET.fromstring(res.text)
            items = root.findall('.//item')
            
            if not items:
                continue
                
            high_prices = []
            volumes = []
            close_prices = []
            dates = []
            
            for item in items:
                data_str = item.get('data')
                parts = data_str.split('|')
                if len(parts) >= 6:
                    dates.append(parts[0])         # 날짜
                    high_prices.append(int(parts[2]))   # 고가
                    close_prices.append(int(parts[4]))  # 종가
                    volumes.append(int(parts[5]))     # 거래량
                    
            if not high_prices:
                continue
                
            high_52w = max(high_prices)
            close_today = close_prices[-1]
            vol_today = volumes[-1]
            date_today = dates[-1]
            
            # 20일 평균 거래량 계산 (오늘 장 제외한 직전 20거래일 평균)
            if len(volumes) >= 21:
                avg_vol_20d = sum(volumes[-21:-1]) / 20
            else:
                avg_vol_20d = sum(volumes) / len(volumes)
                
            dist_to_high = ((high_52w - close_today) / high_52w) * 100
            vol_ratio = vol_today / avg_vol_20d if avg_vol_20d > 0 else 0
            trading_value = (close_today * vol_today) / 100_000_000  # 억원 단위 계산
            
            final_rows.append({
                '티커': ticker,
                '종목명': name,
                '현재가(원)': close_today,
                '52주 최고가': high_52w,
                '최고가 대비 하락률(%)': round(dist_to_high, 2),
                '오늘 거래량': vol_today,
                '20일 평균 거래량': round(avg_vol_20d, 1),
                '거래량 급증 배수': round(vol_ratio, 2),
                '거래대금(억원)': round(trading_value, 1),
                '데이터 기준일': f"{date_today[:4]}-{date_today[4:6]}-{date_today[6:]}"
            })
        except Exception:
            continue
            
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(final_rows)

# 메인 실행 엔진 가동
raw_data = scan_canslim_leaders()

# 4. 실시간 동적 스크리닝 필터 테이블 출력
if not raw_data.empty:
    # 대시보드 상단에 데이터 최종 동기화 일자 표시
    sample_date = raw_data['데이터 기준일'].iloc[0]
    st.info(f"📅 현재 동기화된 최신 시장 데이터 기준일: **{sample_date}**")
    
    # 사용자가 제어하는 슬라이더 필터링 조건 실시간 적용
    cond1 = raw_data['거래대금(억원)'] >= min_value
    cond2 = raw_data['최고가 대비 하락률(%)'] <= high_margin
    cond3 = raw_data['거래량 급증 배수'] >= vol_multiplier
    
    final_df = raw_data[cond1 & cond2 & cond3].reset_index(drop=True)
    
    st.subheader(f"🔍 CANSLIM 조건 만족 주도주 포착 (총 {len(final_df)}개 종목)")
    if not final_df.empty:
        # 52주 최고가에 가장 바짝 붙은 강세주 순서대로 정렬
        final_df = final_df.sort_values(by='최고가 대비 하락률(%)', ascending=True)
        st.dataframe(final_df, use_container_width=True, hide_index=True)
    else:
        st.info("현재 설정된 조건에 완벽히 부합하는 주도주가 없습니다. 왼쪽 사이드바의 스크리닝 조건을 조금 더 완화해 보세요!")
else:
    st.error("데이터 엔진 동기화에 일시적 지연이 발생했습니다. 잠시 후 새로고침(F5)을 시도해 주세요.")
