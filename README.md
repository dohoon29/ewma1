# 🔍 EWMA 기반 실시간 이상 징후 탐지 시스템

## 📋 프로젝트 개요

전력 사용량(W) 및 환경 센서(온도, 조도 등) 데이터를 분석하여 실시간으로 비정상적인 패턴이나 위험한 상황(과전류, 스파이크 등)을 탐지하는 시스템입니다.

### 🎯 **두 가지 사용 방법**
1. **📊 배치 분석**: CSV 파일을 이용한 과거 데이터 분석
2. **⚡ 실시간 탐지**: 기존 FastAPI 서버에 통합하여 실시간 모니터링

### 🧠 **핵심 기술**
- **EWMA(지수 가중 이동 평균)** 기반 패턴 분석
- **실시간 스트리밍** 데이터 처리
- **다중 센서 통합** 분석 (전력, 온도, 습도, 조도)
- **계절별 온열 환경** 이상 탐지

## 🚀 빠른 시작 (기존 FastAPI 서버 통합)

### **⚡ 3줄로 기존 서버에 이상 탐지 추가**

```python
# 1. 패키지 임포트
from anomaly_detector_package import AnomalyDetectorManager

# 2. 서버 시작 시 초기화 (한 번만)
detector = AnomalyDetectorManager("ewma_baseline_ch01.json")

# 3. 기존 엔드포인트에 추가
@app.post("/api/your-endpoint")
async def your_endpoint(data: dict):
    result = await detector.process_data({"power_W": data["power"]})
    return {"anomaly_detected": result.is_anomaly, "events": result.events}
```

### 📦 **필요한 파일들**
기존 FastAPI 서버에 통합하려면 다음 파일들만 복사하세요:

```
📁 기존 서버 프로젝트/
├── anomaly_detector_package.py      # 🎯 메인 패키지 (필수)
├── home_env_power_detector_v3.py    # 🧠 탐지 엔진 (필수)  
├── ewma_baseline_ch01.json          # 📊 베이스라인 데이터 (필수)
└── requirements.txt                 # 📋 의존성 (업데이트)
```

### 🔧 **의존성 설치**
```bash
pip install pandas numpy fastapi
```

---

## 📊 배치 분석 방법 (CSV 파일)

### **요구 사항**
- Python 3.x  
- `pandas`, `numpy` 라이브러리

```bash
pip install pandas numpy
```

### **주요 파일 설명**
- **`run_v3_test.py`**: 배치 분석용 실행 스크립트
- **`home_env_power_detector_v3.py`**: 핵심 탐지 엔진
- **`ewma_baseline_ch01.json`**: 사전 학습된 베이스라인 모델
- **`v3_anomalies_output.csv`**: 분석 결과 저장 파일

## 4. 데이터 파일 형식 (Data File Format)

탐지 모델은 특정 형식의 CSV 파일을 입력으로 받습니다.

### 4.1. 메인 데이터 (`input_csv`)

전력 및 실내 환경 데이터가 포함된 기본 입력 파일입니다.

#### 필수 컬럼
- **타임스탬프**: `timestamp`, `time`, `ts`, `datetime` 중 하나의 컬럼명.
- **전력 사용량 (W)**: `power_w`, `power`, `watts`, `w` 중 하나의 컬럼명.

#### 선택적 컬럼
- **실내 온도 (°C)**: `temp_c`, `room_temp_c`
- **상대 습도 (%)**: `rh`, `humidity`
- **조도 (lux)**: `lux`

#### 예시
```csv
timestamp,power_w,temp_c,rh,lux
2023-10-27T00:00:00,150.5,22.5,45.2,10.0
2023-10-27T00:00:02,151.0,22.5,45.3,10.0
...
```

### 4.2. 외부 날씨 데이터 (`weather_csv` - 선택 사항)

온도 기반 탐지를 위해 선택적으로 사용할 수 있는 외부 날씨 데이터 파일입니다. `run_batch` 함수 사용 시 `weather_csv` 인자에 파일 경로를 지정하여 사용합니다.

#### 필수 컬럼
- **타임스탬프**: `timestamp`, `time`, `ts`, `datetime` 중 하나.
- **외부 온도 (°C)**: `outside_temp_C`, `outdoor_temp_C`, `temp_out_C` 중 하나.

## 5. 이상 탐지 기준 (Anomaly Detection Logic)

탐지되는 이벤트의 종류와 기준은 다음과 같습니다. 모든 기준값은 `Config` 클래스에서 수정할 수 있습니다.

### 5.1. 전력 기반 탐지

- **`power_ewma_anomaly`**: 전력 사용량의 지수 가중 이동 평균(EWMA)을 크게 벗어나는 패턴이 일정 시간 이상 지속될 때 발생합니다. 평소와 다른 전력 사용 패턴을 탐지합니다.
- **`overcurrent_near_limit`**: 전력 사용량을 기반으로 계산된 전류(A)가 설정된 임계값(기본 30A)에 근접하거나 초과할 때 발생합니다. 과부하 위험을 경고합니다.
- **`short_spike_suspect`**: 짧은 순간에 전류가 급격하게 변하거나 매우 높은 수치로 치솟을 때 발생합니다. 전기 합선이나 기기 고장으로 인한 스파이크를 탐지합니다.

### 5.2. 온도 기반 탐지

실내외 온도 및 조도 데이터를 바탕으로 비정상적인 온열 환경을 탐지합니다. (관련 데이터가 모두 제공될 경우에만 동작)

- **여름철 (6-8월)**: 실내 온도가 실외보다 비정상적으로 높을 때 (`1°C` 이상 '경고', `3°C` 이상 '주의').
- **겨울철 (12-2월)**: 실내 온도가 실외보다 충분히 따뜻하지 않을 때 (온도 차 `5°C` 이하 '경고', `3°C` 이하 '주의').
- **재실 판단**: 조도(`lux`)가 특정 값 미만일 경우, 사람이 없는 것으로 간주하여 온도 관련 탐지를 수행하지 않습니다.

## 6. 사용 방법

`run_v3_test.py` 스크립트를 통해 탐지를 실행합니다.

1.  분석하고 싶은 데이터(CSV 파일)를 프로젝트 폴더에 넣습니다.
2.  `run_v3_test.py` 파일을 열어 아래 변수들을 자신의 환경에 맞게 수정합니다.
    - `INPUT_FILE`: 분석할 데이터 파일 이름으로 변경합니다. (예: `'my_new_data.csv'`)
    - `BASELINE_FILE`: 사용할 베이스라인 모델 파일 이름으로 변경합니다. (예: `'my_baseline.json'`)
    - `OUTPUT_FILE`: 결과가 저장될 파일 이름을 지정합니다.
3.  터미널에서 아래 명령어를 실행합니다.
    ```bash
    python run_v3_test.py
    ```
4.  탐지가 완료되면 지정한 `OUTPUT_FILE` 이름으로 결과 파일이 생성됩니다.

## 7. 결과 확인

탐지 결과는 `v3_anomalies_output.csv` (또는 `OUTPUT_FILE`로 지정한 파일)에 저장됩니다.

- **type**: 탐지된 이벤트의 종류 (`short_spike_suspect`, `overcurrent_near_limit` 등)
- **start**: 이벤트 시작 시간
- **end**: 이벤트 종료 시간
- **severity**: 심각도 (`warn` 또는 `alert`)
- **info_json**: 이벤트에 대한 상세 정보 (JSON 형식)

---

## ⚡ 실시간 FastAPI 서버 통합 상세 가이드

### 🎯 **1단계: 필수 파일 복사**

기존 FastAPI 프로젝트에 다음 3개 파일만 복사하세요:

```bash
# 이 저장소에서 복사할 파일들
cp anomaly_detector_package.py /path/to/your/fastapi/project/
cp home_env_power_detector_v3.py /path/to/your/fastapi/project/
cp ewma_baseline_ch01.json /path/to/your/fastapi/project/
```

### 🔧 **2단계: 기존 서버 코드 수정**

#### **최소한의 통합 (3줄 추가)**
```python
# 기존 FastAPI 서버 코드
from fastapi import FastAPI
from anomaly_detector_package import AnomalyDetectorManager  # 1줄 추가

app = FastAPI()
detector = AnomalyDetectorManager("ewma_baseline_ch01.json")  # 1줄 추가

@app.post("/api/sensor-data")  # 기존 엔드포인트
async def receive_sensor_data(data: dict):
    # 기존 로직 그대로 유지
    # ... your existing code ...
    
    # 이상 탐지만 추가
    result = await detector.process_data(data)  # 1줄 추가
    
    return {
        "status": "success",  # 기존 응답
        "anomaly_detected": result.is_anomaly,  # 추가 정보
        "events": result.events if result.is_anomaly else []
    }
```

#### **고급 통합 (자동 알림 포함)**
```python
from fastapi import FastAPI, BackgroundTasks
from anomaly_detector_package import AnomalyDetectorManager

app = FastAPI()

# 이상 탐지 시 자동 호출되는 콜백
async def alert_callback(result):
    if result.is_anomaly:
        # 여기에 알림 로직 추가
        print(f"🚨 이상 탐지! {len(result.events)}개 이벤트")
        # await send_slack_notification(result)
        # await save_to_database(result)

detector = AnomalyDetectorManager(
    baseline_file="ewma_baseline_ch01.json",
    alert_callback=alert_callback  # 자동 알림 설정
)

@app.post("/api/sensor-data")
async def receive_sensor_data(data: dict):
    # 백그라운드에서 이상 탐지 (응답 속도 향상)
    result = await detector.process_data(data)
    
    return {"status": "received", "anomaly_check": "completed"}
```

### 📊 **3단계: 데이터 형식 맞추기**

기존 서버의 데이터 형식을 패키지 형식으로 변환:

```python
@app.post("/api/your-existing-endpoint")
async def your_endpoint(data: YourDataModel):
    # 기존 데이터 형식을 패키지 형식으로 변환
    detection_data = {
        "power_W": data.power_consumption,    # 필수
        "temp_C": data.temperature,           # 선택
        "rh_pct": data.humidity,             # 선택  
        "lux": data.light_level,             # 선택
        "timestamp": data.created_at         # 선택
    }
    
    result = await detector.process_data(detection_data)
    
    # 기존 응답에 이상 탐지 결과 추가
    return {
        **your_existing_response,  # 기존 응답 그대로
        "anomaly_detection": {
            "is_anomaly": result.is_anomaly,
            "event_count": len(result.events),
            "events": result.events
        }
    }
```

### 🔍 **4단계: 모니터링 엔드포인트 추가 (선택)**

```python
@app.get("/api/anomaly-status")
async def get_anomaly_status():
    """이상 탐지 시스템 상태 확인"""
    status = detector.get_status()
    return {
        "detector_status": "active",
        "total_processed": status["total_processed"],
        "total_anomalies": status["total_anomalies"],
        "anomaly_rate": f"{status['anomaly_rate']:.1f}%",
        "uptime_minutes": status["uptime_minutes"]
    }

@app.post("/api/test-anomaly")
async def test_anomaly(test_power: float = 8000):
    """이상 탐지 테스트 (개발용)"""
    result = await detector.process_data({"power_W": test_power})
    return {
        "test_power": test_power,
        "anomaly_detected": result.is_anomaly,
        "events": result.events
    }
```

### 🎛️ **5단계: 설정 커스터마이징 (선택)**

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

### 🚀 **완성된 예시**

```python
from fastapi import FastAPI
from anomaly_detector_package import AnomalyDetectorManager
from pydantic import BaseModel

app = FastAPI(title="Your Existing Server + Anomaly Detection")

# 기존 데이터 모델
class SensorReading(BaseModel):
    device_id: str
    power_consumption: float
    temperature: float = None
    humidity: float = None

# 이상 탐지 매니저 초기화
detector = AnomalyDetectorManager("ewma_baseline_ch01.json")

@app.post("/api/sensor-readings")  # 기존 엔드포인트
async def log_sensor_reading(reading: SensorReading):
    # 기존 로직 (DB 저장 등)
    # await save_to_database(reading)
    
    # 이상 탐지 추가 (3줄)
    detection_data = {
        "power_W": reading.power_consumption,
        "temp_C": reading.temperature
    }
    result = await detector.process_data(detection_data)
    
    # 기존 응답에 이상 탐지 결과 추가
    return {
        "device_id": reading.device_id,
        "status": "logged",
        "timestamp": "...",
        # 이상 탐지 결과 추가
        "anomaly_detected": result.is_anomaly,
        "alert_level": "HIGH" if result.is_anomaly else "NORMAL"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### ✅ **통합 완료 체크리스트**

- [ ] 필수 파일 3개 복사 완료
- [ ] `anomaly_detector_package` 임포트 추가
- [ ] `AnomalyDetectorManager` 초기화
- [ ] 기존 엔드포인트에 `detector.process_data()` 호출 추가
- [ ] 데이터 형식 변환 (power_W 필수)
- [ ] 테스트 실행 (`/api/test-anomaly` 호출)

### 🎯 **핵심 포인트**

1. **기존 코드 영향 최소화**: 단 3줄만 추가하면 완료
2. **검증된 알고리즘**: 기존 탐지 엔진 100% 재사용  
3. **유연한 데이터 형식**: 다양한 키명 자동 인식
4. **비동기 지원**: FastAPI와 완벽 호환
5. **확장 가능**: 콜백, 커스텀 설정 등 고급 기능 지원

**🎉 이제 기존 FastAPI 서버에서 강력한 실시간 이상 탐지를 사용할 수 있습니다!**

---

## 📁 전체 파일 목록 및 용도

### 🎯 **실시간 통합용 파일 (필수 3개)**
```
anomaly_detector_package.py      # 📦 메인 패키지 - 기존 서버에 통합
home_env_power_detector_v3.py    # 🧠 핵심 탐지 엔진 - 검증된 알고리즘
ewma_baseline_ch01.json          # 📊 사전 학습된 베이스라인 데이터
```

### 📊 **배치 분석용 파일**
```
run_v3_test.py                   # 🏃 CSV 파일 배치 분석 실행기
monitor_current_anomalies.csv    # 📈 샘플 데이터 (테스트용)
v3_anomalies_output.csv          # 📋 배치 분석 결과 파일
```

### 🚀 **개발/테스트용 파일**
```
realtime_anomaly_server.py       # 🌐 독립 실행형 실시간 서버 (참고용)
fastapi_integration_example.py   # 📝 통합 예시 코드 (참고용)
test_client.py                   # 🧪 테스트 클라이언트 (개발용)
```

### 📚 **문서 파일**
```
README.md                        # 📖 이 파일 - 전체 사용 가이드
INTEGRATION_GUIDE.md             # 📋 상세 통합 가이드
requirements.txt                 # 📦 Python 의존성 목록
```

### 🎯 **사용 시나리오별 파일 선택**

#### **기존 FastAPI 서버에 통합하려면:**
```bash
# 이 3개 파일만 복사하세요
✅ anomaly_detector_package.py
✅ home_env_power_detector_v3.py  
✅ ewma_baseline_ch01.json
```

#### **독립 실행형 서버를 원한다면:**
```bash
# 이 파일들을 사용하세요
✅ realtime_anomaly_server.py (메인)
✅ home_env_power_detector_v3.py
✅ ewma_baseline_ch01.json
✅ test_client.py (테스트용)
```

#### **과거 데이터 분석을 원한다면:**
```bash
# 이 파일들을 사용하세요  
✅ run_v3_test.py (메인)
✅ home_env_power_detector_v3.py
✅ ewma_baseline_ch01.json
✅ your_data.csv (분석할 데이터)
```

### 💡 **권장 사항**

- **실시간 모니터링**: `anomaly_detector_package.py` 사용 (기존 서버 통합)
- **개발/테스트**: `realtime_anomaly_server.py` 사용 (독립 실행)  
- **데이터 분석**: `run_v3_test.py` 사용 (배치 처리)

**🚀 목적에 맞는 파일을 선택해서 사용하세요!**
