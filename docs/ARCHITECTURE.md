# UIAA Architectural Diagrams

This document contains professional-grade Mermaid diagrams designed for inclusion in the UIAA Technical White Paper or any accompanying documentation. They can be natively embedded into Markdown files or rendered into images for LaTeX using Mermaid tools.

## 1. High-Level System Architecture
This flowchart maps the 6-layer pipeline, highlighting the clear separation between Perception, AI Decision (Orchestration), and Execution.

```mermaid
flowchart TB
    %% Styling
    classDef userNode fill:#2b2d42,stroke:#edf2f4,stroke-width:2px,color:#fff,shape:circle
    classDef perceiver fill:#edf2f4,stroke:#8d99ae,stroke-width:2px,color:#2b2d42
    classDef coreAI fill:#ef233c,stroke:#d90429,stroke-width:3px,color:#fff
    classDef execute fill:#8d99ae,stroke:#2b2d42,stroke-width:2px,color:#fff
    classDef kiosk fill:#edf2f4,stroke:#2b2d42,stroke-width:2px,color:#2b2d42,stroke-dasharray: 5 5

    U((User)):::userNode

    subgraph Layer1 [1. Perception Layer]
        CV[Computer Vision<br/>Presence, Posture, Gaze]:::perceiver
        ASR[ASR Engine<br/>Streaming Audio]:::perceiver
        OCR[OCR Engine<br/>Screen Text & State]:::perceiver
    end

    subgraph Layer2 [2. User Modeling]
        BD[Temporal Decay Model]:::perceiver
        USV[User State Vector]:::perceiver
    end

    subgraph Layer3 [3. AI Decision Engine]
        CBA[Context Bundle Assembler]:::coreAI
        LLM{LLM Zero-Shot<br/>Orchestrator}:::coreAI
        VAL[Output Validator & Parser]:::coreAI
    end

    subgraph Layer4 [4. Execution & Adaptation Layer]
        KAL[Kiosk Abstraction Layer<br/>Commands]:::execute
        AIL[Adaptive Interaction Layer<br/>UI Directives]:::execute
        TTS[TTS Engine<br/>Audio Output]:::execute
    end

    subgraph Layer5 [5. Physical User Interface]
        Backend[(Kiosk Backend / APIs)]:::kiosk
        Display[Adaptive Kiosk Display]:::kiosk
        Speaker[Kiosk Speaker]:::kiosk
    end

    %% Flow
    U -->|Video / Optics| CV
    U -->|Voice| ASR
    CV -->|Behavioral Signals| BD
    BD --> USV
    
    ASR -->|Transcripts & Language| CBA
    USV -->|Live Capability Profile| CBA
    OCR -->|Current Screen State| CBA
    
    CBA -->|Aggregated JSON Prompt| LLM
    LLM -->|Structured Action JSON| VAL
    
    VAL -->|Action: Execute| KAL
    VAL -->|Action: Adapt UI| AIL
    VAL -->|Action: Speak| TTS
    
    KAL -->|Standardized API Call| Backend
    AIL -->|Override Styles| Display
    TTS -->|Speech Output| Speaker
    
    Backend -->|Updates via DOM / Rendering| Display
    
    %% Closed Loop Force
    Display -.->|Closed-Loop Verification| OCR
```

## 2. Real-Time Execution Sequence Diagram
This sequence diagram demonstrates the low-latency closed-loop interaction over time.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant PL as Perception Layer
    participant UME as User Modeling Engine
    participant DE as LLM Decision Engine
    participant KAL as Kiosk Backend Layer
    participant UI as Adaptive UI Layer
    
    User->>PL: Voice: "I want to withdraw 2000" <br/> + Squinting slightly
    activate PL
    PL->>UME: Signal: Vision Challenge Detected (Confidence: 0.8)
    PL->>DE: Audio Transcript + Current OCR Screen Context
    deactivate PL
    
    activate UME
    UME->>UME: Apply Temporal Decay & Update Defaults
    UME->>DE: Output: UserStateVector (Visual_Capability = 0.3)
    deactivate UME
    
    activate DE
    Note over DE: Context Bundle Formed.<br/>LLM Prompt Evaluated (Target <200ms)
    DE->>DE: JSON Output Schema Validation
    DE->>KAL: Command_Directive: WITHDRAW (Amt: 2000)
    DE->>UI: UI_Directive: Increase Font Size x1.5 & Speak Confirmation
    deactivate DE
    
    activate KAL
    KAL-->>KAL: Validate System State & Balance APIs
    deactivate KAL
    
    activate UI
    UI->>User: TTS: "Withdrawing 2000 rupees. Please confirm."
    UI-->>UI: Instantly Adjust Screen Rendering
    deactivate UI
    
    Note over PL,UI: Closed-Loop Verification
    UI-.->>PL: OCR grabs New Rendered Screen
    PL-.->>DE: Screen Update Verified (Awaiting User Confirm)
```

## 3. Data Entities & Context Bundle Model
A class diagram showing the exact data shapes feeding into the LLM and coming out of it. 

```mermaid
classDiagram
    direction TB
    class ContextBundle {
        +String asr_transcript
        +String detected_language
        +UserStateVector current_user_state
        +ScreenState current_screen_content
        +EnvironmentData environmentContext
        +List~ConversationTurn~ history
        +assemble() JSON
    }
    
    class UserStateVector {
        +Float visual_capability
        +Float motor_capability
        +Float cognitive_load
        +String inferred_age_group
        +Float frustration_index
        +List~String~ behavioral_flags
        +decay_old_signals(time_delta)
    }

    class LLMOutput {
        +String internal_reasoning
        +List~Action~ actions
        +ConversationState conversation_state
    }

    class Action {
        <<Interface>>
        +String target_module
        +String directive_type
        +Dict parameters
        +Boolean requires_confirmation
    }

    ContextBundle "1" *-- "1" UserStateVector
    ContextBundle "1" ..> "1" LLMOutput : Orchestrator Infers
    LLMOutput "1" *-- "1..*" Action
```

## 4. Safety Validation & Multi-Tier Fallback Pipeline
This flowchart illustrates the robustness of the system architecture in case of anomalies.

```mermaid
flowchart LR
    classDef process fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#000
    classDef check fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#000
    classDef fail fill:#ffebee,stroke:#c62828,stroke-width:2px,color:#000
    classDef success fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#000

    IN[LLM Raw Action Response]:::process
    
    IN --> JSON[JSON Parse Evaluation]:::check
    JSON -->|Success| Schema[Schema Validation]:::check
    JSON -->|Failure| Retry[Retry Prompt Validation<br/>max 2 times]:::fail
    
    Schema -->|Valid| Business[Business Logic & Limits]:::check
    Schema -->|Invalid| Retry
    
    Retry -->|Retry Success| Schema
    Retry -->|Max Retries Exceeded| Fallback[Trigger Fallback Strategy]:::fail
    
    Business -->|Passes Constraints| EXECUTE[Execute Action safely]:::success
    Business -->|Fails Constraint| Escalation[Reject Action & Re-prompt User]:::fail
```
