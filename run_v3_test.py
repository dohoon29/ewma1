from home_env_power_detector_v3 import run_batch, Config

# --- 설정 ---
INPUT_FILE = 'monitor_current_anomalies.csv'
BASELINE_FILE = 'ewma_baseline_ch01.json'
OUTPUT_FILE = 'v3_anomalies_output.csv'

print(f"V3 탐지 모델을 사용하여 '{INPUT_FILE}' 파일 분석을 시작합니다.")
print(f"베이스라인: '{BASELINE_FILE}'")

# 사용자 정의 설정을 원하면 여기서 Config 객체를 수정할 수 있습니다.
# 예: cfg = Config(ewma_k=3.5, current_limit_A=25.0)
cfg = Config()

# 탐지 실행
results_df = run_batch(
    input_csv=INPUT_FILE,
    baseline_json=BASELINE_FILE,
    cfg=cfg,
    out_csv=OUTPUT_FILE
)

print(f"\n탐지 완료! {len(results_df)}개의 이벤트가 탐지되었습니다.")
print(f"결과가 '{OUTPUT_FILE}' 파일에 저장되었습니다.")
