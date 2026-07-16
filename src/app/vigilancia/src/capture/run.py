# vigilancia/capture/run.py
# Entrypoint del motor de captura (proceso APARTE del API):
#   python -m src.capture.run
from src.capture.supervisor import main

if __name__ == "__main__":
    main()
