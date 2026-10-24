import sys
import os
import subprocess
import time

def main():
    python_exe = sys.executable

    # Пути к запускаемым модулям в подпапках
    web_script = os.path.join("web", "standalone_test.py")
    streamlit_script = os.path.join("dashboard", "streamlit_app.py")

    print("=" * 60)
    print("🚀 Запуск Lichess Tracker и Streamlit Dashboard...")
    print(f"Используется Python: {python_exe}")
    print("=" * 60)

    # 1. Запуск веб-интерфейса FastAPI (порт 8000)
    web_process = subprocess.Popen([python_exe, web_script])

    # 2. Запуск дашборда Streamlit (порт 8501)
    streamlit_cmd = [
        python_exe, "-m", "streamlit", "run", streamlit_script,
        "--server.port=8501",
        "--server.headless=true"
    ]
    streamlit_process = subprocess.Popen(streamlit_cmd)

    print("\n Сервисы успешно запущены:")
    print(" 🌐 Веб-интерфейс:     http://localhost:8000")
    print(" 📊 Streamlit-дашборд: http://localhost:8501")
    print("\nДля остановки обоих сервисов нажмите Ctrl + C\n")

    try:
        while True:
            time.sleep(1)
            if web_process.poll() is not None:
                print("❌ Веб-сервер завершил работу.")
                break
            if streamlit_process.poll() is not None:
                print("❌ Streamlit завершил работу.")
                break
    except KeyboardInterrupt:
        print("\n\n Остановка всех процессов...")
    finally:
        for proc, name in [(web_process, "Web-сервер"), (streamlit_process, "Streamlit")]:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                print(f" {name} остановлен.")
        print("Все сервисы выключены.")

if __name__ == "__main__":
    main()