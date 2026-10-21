import json
import io
import re
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

# -----------------------------
# 페이지 설정
# -----------------------------
st.set_page_config(
    page_title="전국 고령화 단계구분도",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ 전국 고령화 단계구분도")
st.markdown(
    "2026년 6월 기준 전국 시군구별 **65세 이상 인구 비율**을 지도에서 확인합니다."
)

DATA_URL = (
    "https://raw.githubusercontent.com/"
    "first2022-cyber/contents/main/population_ts_yearly_gender.zip"
)
GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "first2022-cyber/contents/main/sigungu_kr.geojson"
)


# -----------------------------
# 데이터 불러오기
# -----------------------------
@st.cache_data(show_spinner="인구 데이터를 불러오는 중...")
def load_population():
    response = requests.get(DATA_URL, timeout=120)
    response.raise_for_status()

    # ZIP 압축 CSV를 pandas로 읽기
    df = pd.read_csv(
        io.BytesIO(response.content),
        compression="zip",
        dtype={"코드": "string"},
        low_memory=False
    )

    required = {"연도", "시도", "시군구", "동", "코드"}
    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"인구 데이터에 필요한 열이 없습니다: {', '.join(sorted(missing))}"
        )

    # 연도는 숫자로 변환
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce")

    # 2026년 자료만 사용
    df = df.loc[df["연도"] == 2026].copy()

    if df.empty:
        raise ValueError("인구 데이터에서 2026년 자료를 찾지 못했습니다.")

    # 코드는 문자열로 처리하고 앞의 5자리를 시군구 코드로 사용
    df["코드"] = df["코드"].astype("string").str.strip()
    df["시군구코드"] = df["코드"].str[:5]

    # 계_로 시작하는 연령별 인구 열만 선택
    total_cols = [
        col for col in df.columns
        if col.startswith("계_")
    ]

    if not total_cols:
        raise ValueError("'계_'로 시작하는 인구 열을 찾지 못했습니다.")

    # 65세 이상 열: 계_65세부터 계_100세 이상까지
    elderly_cols = []

    for col in total_cols:
        match = re.fullmatch(r"계_(\d+)세", col)

        if match and int(match.group(1)) >= 65:
            elderly_cols.append(col)
        elif col == "계_100세 이상":
            elderly_cols.append(col)

    if not elderly_cols:
        raise ValueError("65세 이상 인구 열을 찾지 못했습니다.")

    # 숫자형 변환
    for col in total_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # 읍면동별 65세 이상 인구 및 전체 인구
    df["고령인구"] = df[elderly_cols].sum(axis=1)
    df["전체인구"] = df[total_cols].sum(axis=1)

    # 시군구 코드별 합산
    result = (
        df.groupby("시군구코드", as_index=False)
        .agg(
            고령인구=("고령인구", "sum"),
            전체인구=("전체인구", "sum")
        )
    )

    result = result.loc[result["전체인구"] > 0].copy()
    result["고령화율"] = (
        result["고령인구"] / result["전체인구"] * 100
    )

    # 앞자리 0이 사라지지 않도록 문자열 유지
    result["시군구코드"] = result["시군구코드"].astype("string")

    return result


@st.cache_data(show_spinner="시군구 경계 지도를 불러오는 중...")
def load_geojson():
    response = requests.get(GEOJSON_URL, timeout=120)
    response.raise_for_status()

    geojson = response.json()

    if geojson.get("type") != "FeatureCollection":
        raise ValueError("GeoJSON 형식이 FeatureCollection이 아닙니다.")

    # 모든 경계 코드와 속성 코드를 문자열로 정리
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        code = props.get("코드")

        if code is not None:
            code = str(code).strip()

            # 숫자형으로 저장되어 5자리보다 짧은 경우 앞을 0으로 채움
            if code.isdigit():
                code = code.zfill(5)

            props["코드"] = code

    return geojson


# -----------------------------
# 데이터 처리 및 지도 표시
# -----------------------------
try:
    population = load_population()
    geojson = load_geojson()

    # GeoJSON의 코드와 인구 데이터의 시군구 코드로 매칭
    geo_features = []

    for feature in geojson["features"]:
        props = feature.get("properties", {})
        code = props.get("코드")

        if code is None:
            continue

        code = str(code).strip()

        if code.isdigit():
            code = code.zfill(5)

        props["코드"] = code
        geo_features.append(feature)

    geojson["features"] = geo_features

    # 지도에 실제로 존재하는 코드와 인구 데이터가 있는 코드만 사용
    geo_codes = {
        feature["properties"]["코드"]
        for feature in geojson["features"]
    }

    population["시군구코드"] = population["시군구코드"].astype(str)

    matched = population[
        population["시군구코드"].isin(geo_codes)
    ].copy()

    if matched.empty:
        st.error(
            "인구 데이터와 GeoJSON의 시군구 코드가
