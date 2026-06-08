@echo off
:loop
echo Запуск бота...
py bot.py
echo Бот упал из-за сети. Перезапуск через 3 секунды...
timeout /t 3
goto loop