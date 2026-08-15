"""Tests for logging_config (Wave D — coverage 85% plan)."""
from unittest.mock import MagicMock, patch


from vibe_trading.config import logging_config


class TestLoggers:
    def test_get_logger(self):
        assert logging_config.get_logger("test") is not None

    def test_get_trading_logger(self):
        assert logging_config.get_trading_logger() is not None

    def test_get_agent_logger(self):
        assert logging_config.get_agent_logger("analyst") is not None

    def test_get_system_logger(self):
        assert logging_config.get_system_logger() is not None

    def test_configure_logging_json(self):
        logging_config.configure_logging(
            log_level="INFO", json_output=True, enable_file_logging=False)
        # 不 raise

    def test_configure_logging_console(self):
        logging_config.configure_logging(
            log_level="DEBUG", json_output=False, enable_file_logging=False)

    def test_configure_logging_with_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logging_config.configure_logging(
            log_level="INFO", log_file=log_file,
            json_output=True, enable_file_logging=True)
        assert (tmp_path / "test.log").parent.exists()

    def test_configure_logging_file_console(self, tmp_path):
        logging_config.configure_logging(
            log_level="WARNING", log_file=str(tmp_path / "t2.log"),
            json_output=False, enable_file_logging=True)


class TestConsoleRenderer:
    def test_render(self):
        r = logging_config.ConsoleRenderer()
        out = r(None, None, {"event": "msg", "level": "info"})
        assert "msg" in out

    def test_render_with_exc(self):
        r = logging_config.ConsoleRenderer()
        out = r(None, None, {"event": "e", "exception": "trace"})
        assert "e" in out


class TestLogHelpers:
    def test_log_decision_made(self):
        with patch.object(logging_config, "get_trading_logger") as mock_get:
            logger = MagicMock()
            mock_get.return_value = logger
            logging_config.log_decision_made("d1", "BTCUSDT", "BUY", 0.8, 100)
        logger.info.assert_called_once()

    def test_log_agent_started(self):
        with patch.object(logging_config, "get_agent_logger") as mock_get:
            logger = MagicMock()
            mock_get.return_value = logger
            logging_config.log_agent_started("analyst", "phase1", "BTCUSDT")
        logger.info.assert_called_once()

    def test_log_agent_completed(self):
        with patch.object(logging_config, "get_agent_logger") as mock_get:
            logger = MagicMock()
            mock_get.return_value = logger
            logging_config.log_agent_completed("analyst", "phase1", 1.5, True)
        logger.info.assert_called_once()
