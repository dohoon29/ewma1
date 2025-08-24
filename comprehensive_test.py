#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EWMA 이상 탐지 시스템 종합 테스트 코드

모든 구성 요소가 정상적으로 작동하는지 검증합니다:
1. 배치 분석 시스템 테스트
2. 실시간 패키지 테스트  
3. FastAPI 통합 테스트
4. 데이터 형식 호환성 테스트
5. 성능 테스트

작성자: AI Assistant
버전: v1.0
"""

import asyncio
import json
import time
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Any
import subprocess
import sys
import os

# 테스트 결과 저장
test_results = {
    "timestamp": datetime.now().isoformat(),
    "tests": {},
    "summary": {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "errors": []
    }
}

def log_test(test_name: str, status: str, message: str = "", details: Any = None):
    """테스트 결과 로깅"""
    icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
    print(f"{icon} [{test_name}] {message}")
    
    test_results["tests"][test_name] = {
        "status": status,
        "message": message,
        "details": details,
        "timestamp": datetime.now().isoformat()
    }
    
    test_results["summary"]["total"] += 1
    if status == "PASS":
        test_results["summary"]["passed"] += 1
    else:
        test_results["summary"]["failed"] += 1
        test_results["summary"]["errors"].append(f"{test_name}: {message}")

def test_file_existence():
    """필수 파일 존재 여부 테스트"""
    print("\n" + "="*60)
    print("📁 1. 필수 파일 존재 여부 테스트")
    print("="*60)
    
    required_files = [
        "home_env_power_detector_v3.py",
        "ewma_baseline_ch01.json",
        "anomaly_detector_package.py",
        "run_v3_test.py"
    ]
    
    for file in required_files:
        if os.path.exists(file):
            log_test(f"file_{file}", "PASS", f"파일 존재: {file}")
        else:
            log_test(f"file_{file}", "FAIL", f"파일 없음: {file}")

def test_baseline_loading():
    """베이스라인 파일 로딩 테스트"""
    print("\n" + "="*60)
    print("📊 2. 베이스라인 파일 로딩 테스트")
    print("="*60)
    
    try:
        from home_env_power_detector_v3 import EWMABaseline
        
        baseline = EWMABaseline.from_json("ewma_baseline_ch01.json")
        mean_val = baseline.mean()
        std_val = baseline.std()
        
        if mean_val > 0 and std_val > 0 and baseline.n > 0:
            log_test("baseline_loading", "PASS", 
                    f"베이스라인 로드 성공 - 평균: {mean_val:.1f}W, 표준편차: {std_val:.1f}W, 데이터: {baseline.n:,}개")
        else:
            log_test("baseline_loading", "FAIL", "베이스라인 데이터가 올바르지 않음")
            
    except Exception as e:
        log_test("baseline_loading", "FAIL", f"베이스라인 로딩 실패: {str(e)}")

def test_streaming_detector():
    """스트리밍 탐지기 기본 기능 테스트"""
    print("\n" + "="*60)
    print("🔍 3. 스트리밍 탐지기 기본 기능 테스트")
    print("="*60)
    
    try:
        from home_env_power_detector_v3 import StreamingDetector, EWMABaseline, Config
        
        # 탐지기 초기화
        baseline = EWMABaseline.from_json("ewma_baseline_ch01.json")
        detector = StreamingDetector(baseline, Config())
        
        # 정상 데이터 테스트
        normal_data = [
            {"power_W": 1000, "room_temp_C": 25, "lux": 100},
            {"power_W": 1050, "room_temp_C": 26, "lux": 110},
            {"power_W": 980, "room_temp_C": 24, "lux": 90}
        ]
        
        normal_events = 0
        for i, data in enumerate(normal_data):
            ts = pd.Timestamp.now() + pd.Timedelta(seconds=i*2)
            events = detector.update(
                ts=ts,
                power_W=data["power_W"],
                room_temp_C=data.get("room_temp_C"),
                lux=data.get("lux")
            )
            normal_events += len(events)
        
        log_test("normal_data", "PASS" if normal_events == 0 else "WARN", 
                f"정상 데이터 처리 완료 (이벤트: {normal_events}개)")
        
        # 이상 데이터 테스트
        anomaly_data = [
            {"power_W": 8000, "room_temp_C": 25, "lux": 100},  # 과전류
            {"power_W": 500, "room_temp_C": 25, "lux": 100}    # 급격한 변화
        ]
        
        anomaly_events = 0
        for i, data in enumerate(anomaly_data):
            ts = pd.Timestamp.now() + pd.Timedelta(seconds=(i+10)*2)
            events = detector.update(
                ts=ts,
                power_W=data["power_W"],
                room_temp_C=data.get("room_temp_C"),
                lux=data.get("lux")
            )
            anomaly_events += len(events)
        
        if anomaly_events > 0:
            log_test("anomaly_data", "PASS", f"이상 데이터 탐지 성공 (이벤트: {anomaly_events}개)")
        else:
            log_test("anomaly_data", "FAIL", "이상 데이터를 탐지하지 못함")
            
    except Exception as e:
        log_test("streaming_detector", "FAIL", f"스트리밍 탐지기 테스트 실패: {str(e)}")

async def test_anomaly_detector_package():
    """이상 탐지 패키지 테스트"""
    print("\n" + "="*60)
    print("📦 4. 이상 탐지 패키지 테스트")
    print("="*60)
    
    try:
        from anomaly_detector_package import AnomalyDetectorManager
        
        # 매니저 초기화
        manager = AnomalyDetectorManager(
            baseline_file="ewma_baseline_ch01.json",
            log_level="ERROR"  # 테스트 중에는 로그 최소화
        )
        
        # 정상 데이터 테스트
        normal_result = await manager.process_data({
            "power_W": 1000,
            "temp_C": 25,
            "lux": 100
        })
        
        if not normal_result.is_anomaly:
            log_test("package_normal", "PASS", "패키지 정상 데이터 처리 성공")
        else:
            log_test("package_normal", "WARN", f"정상 데이터에서 이상 탐지: {len(normal_result.events)}개")
        
        # 이상 데이터 테스트
        anomaly_result = await manager.process_data({
            "power_W": 8000,
            "temp_C": 25,
            "lux": 100
        })
        
        if anomaly_result.is_anomaly:
            log_test("package_anomaly", "PASS", f"패키지 이상 데이터 탐지 성공 ({len(anomaly_result.events)}개 이벤트)")
        else:
            log_test("package_anomaly", "FAIL", "패키지가 이상 데이터를 탐지하지 못함")
        
        # 다양한 데이터 형식 테스트
        format_tests = [
            {"power": 1000, "temperature": 25},  # 다른 키명
            {"power_W": 1100},                   # 최소 데이터
            {"power_W": 1050, "temp_C": 26, "rh_pct": 60, "lux": 150}  # 전체 데이터
        ]
        
        format_success = 0
        for i, data in enumerate(format_tests):
            try:
                result = await manager.process_data(data)
                format_success += 1
            except Exception as e:
                log_test(f"format_test_{i}", "FAIL", f"데이터 형식 테스트 실패: {str(e)}")
        
        if format_success == len(format_tests):
            log_test("data_formats", "PASS", "다양한 데이터 형식 처리 성공")
        else:
            log_test("data_formats", "WARN", f"데이터 형식 테스트: {format_success}/{len(format_tests)} 성공")
        
        # 상태 확인 테스트
        status = manager.get_status()
        if status["status"] == "running" and status["total_processed"] > 0:
            log_test("package_status", "PASS", f"패키지 상태 확인 성공 (처리: {status['total_processed']}개)")
        else:
            log_test("package_status", "FAIL", "패키지 상태 확인 실패")
            
    except Exception as e:
        log_test("package_test", "FAIL", f"패키지 테스트 실패: {str(e)}")

def test_batch_processing():
    """배치 처리 시스템 테스트"""
    print("\n" + "="*60)
    print("📊 5. 배치 처리 시스템 테스트")
    print("="*60)
    
    try:
        # 테스트용 CSV 데이터 생성
        test_data = []
        base_time = datetime.now()
        
        for i in range(20):
            timestamp = base_time + timedelta(seconds=i*2)
            if i < 15:  # 정상 데이터
                power = 1000 + (i % 5) * 10
            else:  # 이상 데이터
                power = 8000 if i == 15 else 500
            
            test_data.append({
                "timestamp": timestamp.isoformat(),
                "power_W": power,
                "temp_C": 25 + (i % 3),
                "lux": 100 + (i % 10) * 5
            })
        
        # 테스트 CSV 파일 생성
        test_df = pd.DataFrame(test_data)
        test_csv_file = "test_batch_data.csv"
        test_df.to_csv(test_csv_file, index=False)
        
        # 배치 처리 실행
        from home_env_power_detector_v3 import run_batch
        
        result_df = run_batch(
            input_csv=test_csv_file,
            baseline_json="ewma_baseline_ch01.json",
            out_csv="test_batch_output.csv"
        )
        
        if len(result_df) > 0:
            log_test("batch_processing", "PASS", f"배치 처리 성공 ({len(result_df)}개 이벤트 탐지)")
        else:
            log_test("batch_processing", "WARN", "배치 처리 완료 (이상 이벤트 없음)")
        
        # 테스트 파일 정리
        if os.path.exists(test_csv_file):
            os.remove(test_csv_file)
        if os.path.exists("test_batch_output.csv"):
            os.remove("test_batch_output.csv")
            
    except Exception as e:
        log_test("batch_processing", "FAIL", f"배치 처리 테스트 실패: {str(e)}")

async def test_performance():
    """성능 테스트"""
    print("\n" + "="*60)
    print("⚡ 6. 성능 테스트")
    print("="*60)
    
    try:
        from anomaly_detector_package import AnomalyDetectorManager
        
        manager = AnomalyDetectorManager("ewma_baseline_ch01.json", log_level="ERROR")
        
        # 1000개 데이터 처리 시간 측정
        test_count = 1000
        start_time = time.time()
        
        for i in range(test_count):
            power = 1000 + (i % 100) * 5  # 다양한 전력값
            await manager.process_data({
                "power_W": power,
                "temp_C": 25 + (i % 10),
                "lux": 100
            })
        
        end_time = time.time()
        elapsed = end_time - start_time
        throughput = test_count / elapsed
        
        if throughput > 100:  # 초당 100개 이상 처리
            log_test("performance", "PASS", f"성능 테스트 통과 - {throughput:.0f} 데이터/초 처리")
        else:
            log_test("performance", "WARN", f"성능 주의 - {throughput:.0f} 데이터/초 처리")
        
    except Exception as e:
        log_test("performance", "FAIL", f"성능 테스트 실패: {str(e)}")

def test_integration_example():
    """통합 예시 코드 테스트"""
    print("\n" + "="*60)
    print("🔗 7. FastAPI 통합 예시 테스트")
    print("="*60)
    
    try:
        # 통합 예시가 정상적으로 임포트되는지 테스트
        import fastapi_integration_example
        log_test("integration_import", "PASS", "통합 예시 임포트 성공")
        
        # 패키지가 FastAPI와 호환되는지 테스트
        from fastapi import FastAPI
        from anomaly_detector_package import AnomalyDetectorManager
        
        app = FastAPI()
        detector = AnomalyDetectorManager("ewma_baseline_ch01.json", log_level="ERROR")
        
        @app.get("/test")
        async def test_endpoint():
            result = await detector.process_data({"power_W": 1000})
            return {"test": "success", "anomaly": result.is_anomaly}
        
        log_test("fastapi_compatibility", "PASS", "FastAPI 호환성 확인 완료")
        
    except Exception as e:
        log_test("integration_test", "FAIL", f"통합 테스트 실패: {str(e)}")

def generate_test_report():
    """테스트 결과 보고서 생성"""
    print("\n" + "="*80)
    print("📋 종합 테스트 결과 보고서")
    print("="*80)
    
    summary = test_results["summary"]
    
    print(f"🕐 테스트 시간: {test_results['timestamp']}")
    print(f"📊 총 테스트: {summary['total']}개")
    print(f"✅ 성공: {summary['passed']}개")
    print(f"❌ 실패: {summary['failed']}개")
    
    if summary['failed'] == 0:
        print(f"\n🎉 모든 테스트 통과! 시스템이 정상적으로 작동합니다.")
        overall_status = "PASS"
    else:
        print(f"\n⚠️  {summary['failed']}개 테스트 실패")
        print("실패한 테스트:")
        for error in summary['errors']:
            print(f"   • {error}")
        overall_status = "FAIL"
    
    # 테스트 결과를 JSON 파일로 저장
    with open("test_results.json", "w", encoding="utf-8") as f:
        json.dump(test_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n📄 상세 결과: test_results.json 파일에 저장됨")
    
    return overall_status

async def main():
    """메인 테스트 실행"""
    print("🧪 EWMA 이상 탐지 시스템 종합 테스트 시작")
    print("="*80)
    print(f"📅 테스트 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📁 테스트 디렉토리: {os.getcwd()}")
    print("="*80)
    
    # 순차적으로 모든 테스트 실행
    test_file_existence()
    test_baseline_loading()
    test_streaming_detector()
    await test_anomaly_detector_package()
    test_batch_processing()
    await test_performance()
    test_integration_example()
    
    # 최종 보고서 생성
    overall_status = generate_test_report()
    
    if overall_status == "PASS":
        print("\n🚀 시스템 준비 완료! 프로덕션 환경에서 사용 가능합니다.")
        return 0
    else:
        print("\n🔧 일부 문제가 발견되었습니다. 위의 오류를 확인해주세요.")
        return 1

if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⏹️  테스트가 중단되었습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 테스트 실행 중 오류 발생: {e}")
        sys.exit(1)
