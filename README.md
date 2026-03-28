# Big Screen Monitor Display 3.1.0

<p align="center">
  <img src="usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg" width="128" alt="Big Screen Monitor Display"/>
</p>

<p align="center">
  <b>Dashboard de monitoramento de hardware livre para displays USB LCD</b>
</p>

---

## 📜 A História por trás do Projeto

O **Big Screen Monitor Display** nasceu de um desejo pessoal e de um desafio técnico. **Rafael Ruscher** queria um mini display para compor seu gabinete com informações de hardware em tempo real. Ele encontrou uma telinha pequena e simples, mas ao recebê-la, percebeu um grande obstáculo: o dispositivo era projetado para funcionar exclusivamente no Windows e dependia de softwares proprietários como o AIDA64.

Como usuário fiel de Linux, Rafael não tinha intenção de migrar para o Windows apenas para usar o acessório. Sem encontrar soluções que realmente funcionassem para suas necessidades, e por ser um dispositivo de custo muito baixo, ele acabou deixando a tela guardada em uma gaveta por alguns anos.

Recentemente, ao organizar seu setup, ele reencontrou o mini display. Aquela vontade de vê-lo brilhando dentro do gabinete acendeu novamente. Desta vez, unindo seu conhecimento técnico com o apoio de Inteligência Artificial para acelerar o desenvolvimento, Rafael criou sua própria solução. O resultado é este projeto: uma ferramenta robusta, moderna e, acima de tudo, **Software Livre**. Agora, qualquer usuário Linux pode usar, modificar, distribuir e estudar como o monitor interage com o hardware.

> "Ele é excelente para quem, como eu, não sai do `htop` ou do `gkrellm` e quer um resumo visual sempre à mão." — *Rafael Ruscher*

---

## 🖥️ Displays Suportados

| Display | Tipo | Interface | Resolução | Status |
|---------|------|-----------|-----------|--------|
| **AX206 DPF** | USB Mass Storage | USB HID (pyusb) | 320×240, 480×320 | ✅ Suportado |
| **TURZX / Turing Smart Screen 3.5"** | USB Serial (CDC-ACM) | /dev/ttyACM* (pyserial) | 480×320 | ✅ Suportado (v3.1.0) |

### Sobre o TURZX / Turing Smart Screen

O display **TURZX** (também vendido como "Turing Smart Screen" 3.5") utiliza o chip **QinHeng Electronics** (VID `0x1a86`, PID `0x5722`) com protocolo CDC-ACM via USB Full Speed (12 Mbps). O protocolo é baseado no **Turing Smart Screen Rev A** — comandos de 6 bytes com dados em RGB565 little-endian.

Características do driver:
- **Detecção automática** via VID/PID e número de série ("USB35INCHIPSV2")
- **Tile-based dirty detection** — divide a tela em tiles de 48×20 pixels (160 tiles no total) e envia apenas os que mudaram
- **Envio embaralhado** — tiles sujos são enviados em ordem aleatória para distribuir a atualização visual pela tela inteira
- **Merge horizontal** — tiles adjacentes na mesma linha são mesclados em retângulos maiores para reduzir overhead USB
- **Sleep adaptativo** — 10ms quando há dados, 250ms quando nada mudou

---

## ✨ Funcionalidades Principais (v3.1.0)

Esta versão marca um salto qualitativo no monitoramento, trazendo recursos avançados inspirados em ferramentas clássicas do Linux:

- 🖥️ **Suporte a Turing Smart Screen (TURZX):** Compatibilidade total com displays USB Serial 3.5" baseados em QinHeng Electronics, com driver nativo e detecção automática.
- 🔄 **Orientação Dinâmica:** Troca entre horizontal e vertical em tempo real, com redesenho completo automático ao mudar de orientação.
- 🎨 **Temas Dinâmicos:** Inclui o modo **GKrellM**, com sub-estilos como *Urlicht (Neon Blue)*, *Classic (Fósforo Verde)* e *Cyber-Red*, além do tema **Cyberpunk**.
- 📊 **Gráfico de CPU Avançado:** Visualização em ondas que se movem da direita para a esquerda, com camadas sobrepostas diferenciando o uso de **Usuário** (User Space) e **Sistema** (Kernel Space).
- 🎮 **Suporte Multi-GPU:** Monitoramento completo de múltiplas placas de vídeo simultâneas (AMD, Intel, NVIDIA) com sensores de temperatura, memória, potência (PPT) e carga de Encode/Decode.
- 🔠 **Letreiro Marquee:** Nomes grandes de GPUs ou do Kernel agora passam como um letreiro deslizante (bounce effect) para garantir visibilidade total.
- 📱 **Modo Retrato Inteligente:** Ajuste automático para telas verticais com layout inteligente de 2 colunas.
- ⚙️ **Interface de Configuração Adwaita:** Janela moderna e acessível (GTK4/Adwaita) para personalizar todas as opções, brilho e módulos visíveis.
- 🌐 **Rede e Sensores:** Tráfego RX/TX em tempo real, temperaturas de cores dinâmicas e monitoramento de conexões.
- 🐧 **Logo da Distro:** Suporte automático a logos em PNG e SVG (via `rsvg-convert`), com detecção do sistema operacional.
- 🚀 **Intro Rápida:** Animação de introdução otimizada (~3 segundos).

---

## 🔧 Instalação

### Arch Linux / BigLinux
A forma recomendada é através do PKGBUILD incluso:

```bash
cd pkgbuild
makepkg -si
```

### Estrutura de Diretórios
O projeto segue o padrão organizacional do **BigLinux Settings**:
- `usr/`: Binários, serviços de sistema, arquivos .desktop e a lógica em Python.
- `locale/`: Arquivos de tradução (PO/POT).
- `pkgbuild/`: Arquivos para empacotamento oficial.

---

## 📦 Dependências

- `python` >= 3.10
- `python-pillow` (Renderização de imagem)
- `python-psutil` (Coleta de estatísticas)
- `python-pyusb` (Comunicação USB — displays AX206)
- `python-pyserial` (Comunicação serial — displays Turing/TURZX)
- `python-numpy` (Conversão RGB565 e detecção de tiles sujos)
- `librsvg` (Suporte a ícones e logos vetoriais SVG)
- `lm_sensors` (Leitura de sensores de hardware)

---

## 📄 Licença

Este software é distribuído sob a licença **GPL-3.0**. O código é aberto para estudo, modificação e distribuição, fortalecendo a comunidade de software livre brasileira.

---

## 👤 Desenvolvedor

**Rafael Ruscher** (Equipe BigLinux)  
[GitHub do Projeto](https://github.com/biglinux/big-screen-monitor-display)
