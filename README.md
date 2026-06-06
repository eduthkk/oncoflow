# OncoFlow — Agenda de Boxes de Infusão | V5 EVENTOS

Sistema local em Python/Streamlit para gerenciamento de agenda de boxes de infusão, agora com linha do tempo operacional do atendimento.

## O que tem nesta versão

- Cadastro de pacientes com sistema de prontuário obrigatório: Tasy ou MV.
- Código de prontuário obrigatório, com validação de duplicidade por sistema + prontuário.
- Convênio obrigatório por lista suspensa.
- Edição de paciente.
- Importação de pacientes por CSV.
- Cadastro de boxes e convênios.
- Agendamento por tempo de infusão.
- Protocolo/Pedido, Ciclo e D do ciclo.
- Bloqueio de conflito de box.
- Bloqueio de paciente em horários sobrepostos.
- Bloqueio do mesmo D duplicado no mesmo paciente/protocolo/ciclo.
- Bloqueio de D diferente na mesma data para o mesmo paciente/protocolo/ciclo.
- Edição completa de agendamento.
- Alteração rápida de status direto na visão da agenda do dia.
- Registro de eventos operacionais do atendimento.
- Linha do tempo por agendamento.
- Relatório operacional com tempos reais: alocação, pré-QT, espera farmácia, início/fim real da infusão, pausas/intercorrências e liberação.
- Exportação do relatório operacional em Excel.

## Eventos operacionais disponíveis

- Paciente alocado no box
- Pré-QT iniciada
- Pré-QT finalizada — aguardando medicamento da farmácia
- Medicamento recebido da farmácia
- Infusão iniciada
- Infusão pausada por intercorrência
- Infusão retomada
- Infusão finalizada
- Paciente liberado
- Intercorrência registrada
- Observação operacional

## Como rodar

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Ou execute `INICIAR_ONCOFLOW.bat`.

## Observação

Esta versão ainda usa SQLite local para prototipação. Para produção, o ideal é migrar para SharePoint Lists, Azure SQL/PostgreSQL ou Dataverse com autenticação corporativa.
