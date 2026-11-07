"""utils.message_template 消息模板测试。"""
from utils.message_template import MessageTemplate


class TestEscape:
    def test_escape_markdown(self):
        assert MessageTemplate._escape_markdown("a*b_c") == "a\\*b\\_c"
        assert MessageTemplate._escape_markdown("#标题") == "\\#标题"

    def test_escape_html(self):
        assert MessageTemplate._escape_html("<tag>&\"'") == "&lt;tag&gt;&amp;&quot;&apos;"

    def test_escape_non_string(self):
        assert MessageTemplate._escape_markdown(123) == "123"
        assert MessageTemplate._escape_html(None) == "None"
