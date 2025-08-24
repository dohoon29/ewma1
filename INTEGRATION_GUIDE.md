# 🔌 이상 탐지 패키지 통합 가이드

기존 FastAPI 서버에 EWMA 기반 이상 탐지 기능을 쉽게 추가하는 방법을 설명합니다.

## 📦 **패키지 구조**

```
이상탐지/
├── anomaly_detector_package.py      # 📦 메인 패키지
├── fastapi_integration_example.py   # 📋 통합 예시
├── home_env_power_detector_v3.py    # 🧠 핵심 탐지 엔진
├── ewma_baseline_ch01.json          # 📊 베이스라인 데이터
└── requirements.txt                 # 📋 의존성
```

## 🚀 **빠른 시작**

### **1단계: 패키지 임포트**
```python
from anomaly_detector_package import AnomalyDetectorManager
```

### **2단계: 매니저 초기화**
```python
# 서버 시작 시 한 번만 실행
detector_manager = AnomalyDetectorManager(
    baseline_file="ewma_baseline_ch01.json",
    log_level="INFO"
)
```

### **3단계: 기존 엔드포인트에 추가**
```python
@app.post("/api/your-existing-endpoint")
async def your_endpoint(data: YourDataModel):
    # 기존 로직
    # ... your existing code ...
    
    # 이상 탐지 추가 (3줄만 추가하면 됨!)
    detection_data = {"power_W": data.power, "temp_C": data.temperature}
    result = await detector_manager.process_data(detection_data)
    
    # 응답에 탐지 결과 포함
    return {
        "your_existing_response": "...",
        "anomaly_detected": result.is_anomaly,
        "events": result.events
    }
```

## 📋 **상세 통합 방법**

### **방법 1: 최소한의 통합 (추천)**

기존 코드 변경을 최소화하면서 이상 탐지 추가:

```python
from fastapi import FastAPI
from anomaly_detector_package import AnomalyDetectorManager

app = FastAPI()

# 전역 변수로 매니저 선언
detector = None

@app.on_event("startup")
async def startup():
    global detector
    detector = AnomalyDetectorManager("ewma_baseline_ch01.json")

@app.post("/api/sensor-data")  # 기존 엔드포인트
async def receive_data(data: dict):
    # 기존 로직 그대로 유지
    # ... your existing code ...
    
    # 이상 탐지만 추가
    if detector and "power_W" in data:
        result = await detector.process_data(data)
        if result.is_anomaly:
            print(f"🚨 이상 탐지: {len(result.events)}개 이벤트")
    
    return {"status": "success"}  # 기존 응답 그대로
```

### **방법 2: 콜백 활용**

이상 탐지 시 자동으로 알림 처리:

```python
async def alert_callback(result):
    """이상 탐지 시 자동 호출"""
    # Slack 알림
    await send_slack_message(f"🚨 이상 탐지: {result.events}")
    
    # DB 저장
    await save_anomaly_to_db(result)
    
    # 이메일 발송
    await send_email_alert(result)

detector = AnomalyDetectorManager(
    baseline_file="ewma_baseline_ch01.json",
    alert_callback=alert_callback  # 콜백 등록
)
```

### **방법 3: 백그라운드 태스크**

응답 속도를 위해 이상 탐지를 백그라운드에서 처리:

```python
from fastapi import BackgroundTasks

async def background_anomaly_check(data: dict):
    """백그라운드에서 이상 탐지 수행"""
    result = await detector.process_data(data)
    if result.is_anomaly:
        # 이상 탐지 시 처리 로직
        await handle_anomaly(result)

@app.post("/api/sensor-data")
async def receive_data(data: dict, background_tasks: BackgroundTasks):
    # 즉시 응답 (기존 로직)
    response = {"status": "received", "timestamp": datetime.now()}
    
    # 백그라운드에서 이상 탐지
    background_tasks.add_task(background_anomaly_check, data)
    
    return response
```

## 🔧 **데이터 형식 변환**

기존 서버의 데이터 형식을 패키지 형식으로 변환:

```python
# 기존 서버 데이터 형식
existing_data = {
    "device_id": "sensor_001",
    "power": 1000,           # power_W로 변환 필요
    "temperature": 25,       # temp_C로 변환 필요
    "humidity": 60,          # rh_pct로 변환 필요
    "timestamp": "2024-01-01T00:00:00Z"
}

# 패키지용으로 변환
detection_data = {
    "power_W": existing_data["power"],
    "temp_C": existing_data["temperature"],
    "rh_pct": existing_data["humidity"],
    "timestamp": existing_data["timestamp"]
}

result = await detector.process_data(detection_data)
```

## 📊 **탐지 결과 활용**

```python
result = await detector.process_data(data)

# 기본 정보
print(f"이상 여부: {result.is_anomaly}")
print(f"이벤트 수: {len(result.events)}")

# 상세 이벤트 정보
for event in result.events:
    print(f"유형: {event['type']}")
    print(f"심각도: {event['severity']}")
    print(f"상세: {event['info']}")

# 통계 정보
stats = result.stats
print(f"처리된 데이터: {stats['total_processed']}개")
print(f"탐지된 이상: {stats['total_anomalies']}개")
print(f"현재 평균 전력: {stats['current_mean_W']}W")
```

## 🎯 **실제 적용 예시**

### **스마트 홈 시스템**
```python
@app.post("/api/home/power-usage")
async def log_power_usage(data: PowerUsageModel):
    # 기존: DB 저장
    await db.save_power_data(data)
    
    # 추가: 이상 탐지
    result = await detector.process_data({
        "power_W": data.power_consumption,
        "temp_C": data.room_temperature
    })
    
    # 이상 시 스마트 홈 알림
    if result.is_anomaly:
        await smart_home.send_notification("전력 사용량 이상 감지!")
    
    return {"saved": True, "anomaly_check": result.is_anomaly}
```

### **산업용 모니터링**
```python
@app.post("/api/factory/equipment-status")
async def monitor_equipment(data: EquipmentData):
    # 기존: 장비 상태 기록
    await equipment_db.update_status(data)
    
    # 추가: 이상 탐지
    result = await detector.process_data({
        "power_W": data.power_consumption,
        "temp_C": data.operating_temperature
    })
    
    # 이상 시 즉시 대응
    if result.is_anomaly:
        await maintenance.create_alert(data.equipment_id, result.events)
        await notify_operators(f"장비 {data.equipment_id} 이상 감지")
    
    return {"status": "monitored", "alerts": len(result.events)}
```

## ⚙️ **설정 커스터마이징**

```python
from anomaly_detector_package import Config

# 커스텀 설정
custom_config = Config(
    ewma_k=2.5,              # 더 민감하게 (기본: 3.0)
    current_limit_A=25.0,    # 전류 제한 낮춤 (기본: 30.0)
    spike_delta_A=8.0        # 스파이크 임계값 낮춤 (기본: 10.0)
)

detector = AnomalyDetectorManager(
    baseline_file="ewma_baseline_ch01.json",
    config=custom_config
)
```

## 🔍 **디버깅 및 모니터링**

```python
# 상세 로그 활성화
detector = AnomalyDetectorManager(
    baseline_file="ewma_baseline_ch01.json",
    log_level="DEBUG"  # DEBUG, INFO, WARNING, ERROR
)

# 상태 모니터링 엔드포인트 추가
@app.get("/api/anomaly-detector-status")
async def detector_status():
    return detector.get_status()

# 통계 초기화 (필요시)
@app.post("/api/reset-anomaly-stats")
async def reset_stats():
    detector.reset_stats()
    return {"message": "통계가 초기화되었습니다"}
```

## 🚨 **주의사항**

1. **메모리 사용**: 탐지기는 상태를 유지하므로 서버당 하나의 인스턴스만 생성
2. **베이스라인 파일**: `ewma_baseline_ch01.json` 파일이 필요
3. **비동기 처리**: `await detector.process_data()` 사용 (동기 버전: `process_data_sync()`)
4. **오류 처리**: 탐지 실패 시에도 기존 로직은 정상 동작하도록 구현

## 📞 **문제 해결**

### **자주 발생하는 문제들**

1. **베이스라인 파일 없음**
   ```
   ❌ 오류: [Errno 2] No such file or directory: 'ewma_baseline_ch01.json'
   ✅ 해결: 파일 경로 확인 및 파일 존재 여부 확인
   ```

2. **잘못된 데이터 형식**
   ```python
   # ❌ 잘못된 형식
   data = {"power": "1000"}  # 문자열
   
   # ✅ 올바른 형식  
   data = {"power_W": 1000.0}  # 숫자
   ```

3. **동기/비동기 혼용**
   ```python
   # ❌ 잘못된 사용
   result = detector.process_data(data)  # await 없음
   
   # ✅ 올바른 사용
   result = await detector.process_data(data)  # await 사용
   ```

이제 기존 FastAPI 서버에 **3줄만 추가**해서 강력한 이상 탐지 기능을 사용할 수 있습니다! 🚀
