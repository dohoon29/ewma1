#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EWMA 기반 이상 탐지 시스템 v3 실행 스크립트

이 스크립트는 home_env_power_detector_v3.py에 구현된 이상 탐지 엔진을 사용하여
전력 사용량 및 환경 센서 데이터에서 이상 징후를 탐지합니다.

주요 기능:
- EWMA(Exponentially Weighted Moving Average) 기반 전력 패턴 이상 탐지
- 과전류 및 전류 스파이크 탐지
- 계절별 실내외 온도 차이 기반 열환경 이상 탐지
- 조도 센서 기반 재실 여부 판단

사용법:
1. INPUT_FILE, BASELINE_FILE, OUTPUT_FILE 경로를 수정
2. 필요시 Config 객체를 통해 탐지 파라미터 조정
3. python run_v3_test.py 실행

작성자: AI Assistant
버전: v3.0
마지막 수정: 2024
"""

from home_env_power_detector_v3 import run_batch, Config # 핵심 탐지 엔진과 설정 클래스 임포트
import sys
import os
from datetime import datetime

# =============================================================================
# 설정 섹션 - 사용자 수정 구역
# =============================================================================

# 입력 데이터 파일 설정
# 분석할 CSV 파일 경로 (필수 컬럼: timestamp, power_W)
INPUT_FILE = 'monitor_current_anomalies.csv'

# 베이스라인 모델 파일 설정  
# 사전 학습된 EWMA 통계 정보가 저장된 JSON 파일
BASELINE_FILE = 'ewma_baseline_ch01.json'

# 출력 결과 파일 설정
# 탐지된 이상 징후 이벤트가 저장될 CSV 파일
OUTPUT_FILE = 'v3_anomalies_output.csv'


def main():
    """
    메인 실행 함수
    이상 탐지 시스템을 초기화하고 실행합니다.
    """
    print("="*80)
    print("📊 EWMA 기반 이상 탐지 시스템 v3.0")
    print("="*80)
    print(f"🔍 분석 대상 파일: {INPUT_FILE}")
    print(f"🧠 베이스라인 모델: {BASELINE_FILE}")
    print(f"💾 결과 저장 위치: {OUTPUT_FILE}")
    print(f"🕐 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-"*80)
    
    # 파일 존재 여부 확인
    if not os.path.exists(INPUT_FILE):
        print(f"❌ 오류: 입력 파일을 찾을 수 없습니다: {INPUT_FILE}")
        sys.exit(1)
        
    if not os.path.exists(BASELINE_FILE):
        print(f"❌ 오류: 베이스라인 파일을 찾을 수 없습니다: {BASELINE_FILE}")
        sys.exit(1)

    # 탐지 파라미터 설정
    # 기본 설정을 사용하거나, 필요에 따라 아래 파라미터들을 조정할 수 있습니다:
    # 
    # 주요 파라미터 설명:
    # - ewma_k: EWMA Z-스코어 임계값 (기본 3.0, 높을수록 덜 민감)
    # - current_limit_A: 전류 제한 임계값 (기본 30.0A)
    # - spike_delta_A: 스파이크 탐지 임계값 (기본 10.0A)
    # - ewma_sustain_sec: 이상 상태 지속 시간 (기본 10초)
    #
    # 예시: 더 민감한 탐지를 원할 경우
    # cfg = Config(ewma_k=2.5, current_limit_A=25.0, spike_delta_A=8.0)
    
    cfg = Config()  # 기본 설정 사용
    
    print("⚙️  탐지 설정:")
    print(f"   - EWMA 임계값 (k): {cfg.ewma_k}")
    print(f"   - 전류 제한: {cfg.current_limit_A}A")
    print(f"   - 스파이크 임계: {cfg.spike_delta_A}A")
    print(f"   - 이상 지속 시간: {cfg.ewma_sustain_sec}초")
    print("-"*80)

    # 이상 탐지 엔진 실행
    print("🚀 이상 탐지 엔진 시작...")
    print()
    
    try:
        # run_batch 함수 호출 - 메인 탐지 로직 실행
        results_df = run_batch(
            input_csv=INPUT_FILE,        # 분석할 데이터 파일
            baseline_json=BASELINE_FILE, # 사전 학습된 베이스라인
            cfg=cfg,                     # 탐지 설정
            out_csv=OUTPUT_FILE          # 결과 저장 파일
        )
    except Exception as e:
        print(f"❌ 오류 발생: {str(e)}")
        print("📝 다음 사항들을 확인해주세요:")
        print("   1. 입력 파일의 형식이 올바른지 (timestamp, power_W 컬럼 포함)")
        print("   2. 베이스라인 파일이 손상되지 않았는지")
        print("   3. 필요한 라이브러리가 설치되어 있는지 (pandas, numpy)")
        sys.exit(1)

    print()
    print("="*80)
    print("🎉 탐지 완료!")
    print("="*80)
    print(f"📊 총 {len(results_df)}개의 이상 이벤트가 탐지되었습니다.")
    print(f"💾 결과 파일: {OUTPUT_FILE}")
    print(f"🕑 완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 탐지 결과 상세 분석 및 출력
    if not results_df.empty:
        print("\n📋 탐지된 이벤트 상세 분석:")
        print("-"*50)
        
        # 이벤트 유형별 분석
        event_summary = results_df.groupby(['type', 'severity']).size().reset_index(name='count')
        for event_type in results_df['type'].unique():
            type_events = event_summary[event_summary['type'] == event_type]
            total_count = type_events['count'].sum()
            print(f"\n🔴 {event_type}: {total_count}건")
            for _, row in type_events.iterrows():
                severity_icon = "🚨" if row['severity'] == 'alert' else "⚠️"
                print(f"   {severity_icon} {row['severity']}: {row['count']}건")
        
        # 심각도별 요약
        severity_summary = results_df['severity'].value_counts()
        print(f"\n📊 심각도별 요약:")
        for severity, count in severity_summary.items():
            icon = "🚨" if severity == 'alert' else "⚠️"
            print(f"   {icon} {severity.upper()}: {count}건")
            
        print(f"\n📝 자세한 내용은 '{OUTPUT_FILE}' 파일을 확인해주세요.")
        
    else:
        print("\n✨ 좋은 소식! 이상 징후가 발견되지 않았습니다.")
        print("🔍 모든 전력 사용 패턴과 환경 센서 데이터가 정상 범위 내에 있습니다.")
    
    print("\n" + "="*80)
    print("🚀 프로그램 종료")
    print("="*80)


if __name__ == "__main__":
    """
    스크립트가 직접 실행될 때만 main() 함수를 호출
    다른 모듈에서 import할 때는 실행되지 않음
    """
    main()
