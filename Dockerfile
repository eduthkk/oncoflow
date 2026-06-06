FROM python:3.11-slim
 
WORKDIR /app
 
# Copia e instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
# Copia o resto do ateliê (incluindo a pasta .streamlit e o banco .db)
COPY . .
 
EXPOSE 8501
 
# O comando mágico para dar a partida
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]