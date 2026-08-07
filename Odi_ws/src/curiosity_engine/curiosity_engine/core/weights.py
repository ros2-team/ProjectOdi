# # 점수 계산 가중치
# WEIGHT_NOVELTY = 0.5      #참신성
# WEIGHT_UNCERTAINTY = 0.5  #불확실성 
# WEIGHT_CHANGE = 1.2       #객체 상태변화

# # 행동 결정 임계값
# THRESHOLD_APPROACH = 0.7    #접근해서 상세조사 
# THRESHOLD_OBSERVE = 0.4     #거리두고 관찰

# [curiosity_engine/core/weights.py]

MAX_NOVELTY_SCORE = 0.40       # 참신성 최대 배점
MAX_VISIT_SCORE = 0.20         # 방문 횟수 최대 배점
MAX_CHANGE_SCORE = 0.20        # 변화 감지 최대 배점
MAX_UNCERTAINTY_SCORE = 0.20   # 불확실성 최대 배점