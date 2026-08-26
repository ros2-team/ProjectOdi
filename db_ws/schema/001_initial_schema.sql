
CREATE DATABASE IF NOT EXISTS odi_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE odi_db;

-- 탐험미션
CREATE TABLE IF NOT EXISTS missions (
    session_id VARCHAR(100) PRIMARY KEY,

    status VARCHAR(30) NOT NULL,
    detail TEXT,

    started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    completed_at DATETIME(6),
    updated_at DATETIME(6) NOT NULL
        DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6)
);

-- 물건 상세 관찰 기록
CREATE TABLE IF NOT EXISTS observations (

    memory_id CHAR(36) PRIMARY KEY,

    session_id VARCHAR(100) NOT NULL,
    detection_id VARCHAR(100) NOT NULL,
    success BOOLEAN NOT NULL DEFAULT TRUE,

    object_name VARCHAR(255) NOT NULL,
    object_primary_color VARCHAR(100),
    object_secondary_color VARCHAR(100),
    object_material VARCHAR(100),
    object_shape VARCHAR(100),
    object_condition VARCHAR(100),

    object_special_features JSON,
    raw_json LONGTEXT,

    image_paths JSON,
    representative_image_path VARCHAR(1024),

    diary_summary TEXT,

    started_at DATETIME(6),
    completed_at DATETIME(6),
    stored_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    failure_reason TEXT,

    CONSTRAINT fk_observations_session
        FOREIGN KEY (session_id)
        REFERENCES missions(session_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT uq_observation_session_detection
        UNIQUE (session_id, detection_id),

    INDEX idx_observations_session(session_id),
    INDEX idx_observations_object_name(object_name),
    INDEX idx_observations_material(object_material),
    INDEX idx_observations_shape(object_shape)
);
-- 미션 종료 후 생성된 탐험 일기
CREATE TABLE IF NOT EXISTS diaries (

    diary_id CHAR(36) PRIMARY KEY,

    session_id VARCHAR(100) NOT NULL,
    diary_text LONGTEXT NOT NULL,
    model_name VARCHAR(100),

    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),

    CONSTRAINT fk_diaries_session
        FOREIGN KEY (session_id)
        REFERENCES missions(session_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,

    CONSTRAINT uq_diary_session
        UNIQUE (session_id),

    INDEX idx_diaries_created_at (created_at)
);



