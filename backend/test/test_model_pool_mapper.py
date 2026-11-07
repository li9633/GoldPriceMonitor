"""mapper.model_pool_mapper API Key 加密与解密测试。"""
import sqlite3

from mapper.model_pool_mapper import ModelPoolMapper, _decrypt_api_key
from utils.crypto import encrypt_value


class TestDecryptApiKey:
    def test_ciphertext_decrypts(self):
        cipher = encrypt_value("sk-real-key")
        assert _decrypt_api_key(cipher) == "sk-real-key"

    def test_legacy_env_var_treated_as_unset(self):
        # 改造前的明文存的是环境变量名（如 GLM_API_KEY，非真实 Key），应视为未配置
        assert _decrypt_api_key("GLM_API_KEY") == ""

    def test_empty_treated_as_unset(self):
        assert _decrypt_api_key("") == ""


class TestApiKeyEncryptionAtRest:
    def test_insert_encrypts_and_read_decrypts(self, tmp_db):
        m = ModelPoolMapper(tmp_db)
        m.init_tables()
        m.insert_provider("test", "https://api.test", "sk-secret", 30, 0)
        prov = m.get_provider_by_name("test")
        assert prov["api_key"] == "sk-secret"

    def test_insert_plaintext_stored_as_ciphertext(self, tmp_db):
        m = ModelPoolMapper(tmp_db)
        m.init_tables()
        m.insert_provider("test", "https://api.test", "sk-secret", 30, 0)
        conn = sqlite3.connect(tmp_db)
        raw = conn.execute(
            "SELECT api_key FROM model_providers WHERE name='test'"
        ).fetchone()[0]
        conn.close()
        assert raw.startswith("enc:")
