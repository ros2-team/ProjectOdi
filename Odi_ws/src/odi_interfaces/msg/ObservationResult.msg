# DB 저장과 일기장 산출에 사용할 상세 정보
string detection_id
string detector_class
bool success

string[] image_paths
string representative_image_path

odi_interfaces/SemanticLabel detailed_label
string diary_summary

bool saved_to_database
string memory_id

builtin_interfaces/Time started_at
builtin_interfaces/Time completed_at

string failure_reason
