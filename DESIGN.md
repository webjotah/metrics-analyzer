# DESIGN SYSTEM: Running Metrics Analyzer (Amazfit Active 2)

## 1. Visual World & Direction
- **Archetype**: Athletic Telemetry & Sports Intelligence Studio.
- **Reference Inspiration**: `site-references/Inspo1.webp` & `site-references/a0df983e7e46faebbf14ee4dd9737f51.webp`.
- **Mode**: Operate (Telemetry & Data Analysis) + Read (AI Coach Didactic Report).
- **Core Aesthetic**: Deep obsidian/charcoal surfaces with high-energy Athletic Sports Orange (`#FF5500`), laser-sharp typography, and fluid data visualization without visual clutter or raw unstructured dumps.

## 2. Color System
- **Background Root**: `#0A0B0E` (Deep athletic matte black)
- **Surface Level 1 (Sidebar & Cards)**: `#12141A` (Clean carbon tile)
- **Surface Level 2 (Nested Panels / Hover / Headers)**: `#181A22`
- **Surface Level 3 (Inputs / Code / Dark Traces)**: `#0E1015`
- **Hairline Borders**: `#232632` (Subtle 1px precision)
- **Main Sport Accent**:
  - `Primary Orange`: `#FF5500` (Pantone 021C / Garmin Active Orange)
  - `Orange Hover`: `#FF6E26`
  - `Orange Soft Background`: `rgba(255, 85, 0, 0.12)`
  - `Orange Border Accent`: `rgba(255, 85, 0, 0.35)`
- **Data Accents**:
  - `Recovery / Positive Green`: `#10B981` (Emerald)
  - `Alert / Attention Amber`: `#F59E0B`
  - `Pace / Heart Rate Coral`: `#F43F5E`
  - `Cadence / Dynamic Violet`: `#818CF8`
  - `Altimetry / Neutral Slate`: `#64748B`
- **Typography Colors**:
  - `Text Hero / Primary`: `#F8FAFC` (High contrast pure white)
  - `Text Body`: `#CBD5E1` (Readable slate)
  - `Text Muted / Labels`: `#848B9D` (Neutral athletic grey)

## 3. Typography (Guardrails: NO Inter)
- **Headings & UI Sans**: `'Plus Jakarta Sans', -apple-system, sans-serif`
- **Metrics, Figures & Telemetry**: `'JetBrains Mono', 'Space Grotesk', monospace` with `font-variant-numeric: tabular-nums;`
- **Weights**: 400 (Body), 500 (Medium), 600 (Semibold), 700 (Bold), 800 (Metrics Extrabold)
- **Tracking**: `-0.02em` on headings; `+0.06em` uppercase on metric tags and table headers.

## 4. Geometry & Radii (Guardrails: NO Giant Pills, NO Bland Gradients)
- **Card Radius**: `8px` (crisp, engineered sports hardware feel)
- **Buttons & Inputs**: `6px` (min-height: 42px for touch compliance)
- **Badges & Tags**: `4px` (crisp rectangular with subtle border)
- **Borders & Inset Lighting**: 1px solid `#232530` paired with `box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.07), 0 8px 24px -4px rgba(0, 0, 0, 0.45);`
- **Atmospheric Glow**: Sutil gradiente radial âmbar/laranja em cards de destaque (`radial-gradient(circle at 95% 5%, rgba(255, 85, 0, 0.07), transparent 60%)`).
- **Icons**: Author-crafted inline SVG vector icons with consistent 1.8px stroke width (no informal emojis).

## 5. Micro-Visualizações & AI Cockpit (Inspiração site-references/)
- **Stat Cards com Micro-Sparklines**: Cada cartão didático incorpora uma mini-sparkline SVG com preenchimento gradiente suave no canto direito, exibindo a variação real da métrica no treino (pace, FC, cadência, potência).
- **AI Coach Cockpit**:
  - Módulo interativo com chips de ações rápidas (`⚡ Cadência & Passada`, `❤️ Deriva & Fadiga`, `⏱️ Tiros`, `👟 Próximo Treino`).
  - Leitor com opção de expansão e recolhimento sem quebrar a visão dos gráficos e tabelas.
  - Zero alteração de prompt ou retorno da IA (o texto original do Gemini é preservado 100%).
- **Matriz Segmentada de Equalizador (Tiros)**: Colunas segmentadas por tiro com cores pelas zonas de FC (Z1 azul, Z2 verde, Z3 amarelo, Z4 laranja, Z5 vermelho) no estilo da matriz de blocos de `Inspo1.webp`.
- **Medidor de Queda Cardíaca (Recovery Drop)**: Indicador visual em verde na tabela de pausas exibindo a velocidade de recuperação cardiovascular.
