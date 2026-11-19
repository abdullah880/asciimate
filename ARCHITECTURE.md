# Architecture Overview

This repository is a modular Python application built around a one-time image conversion pipeline and a Pygame-based delta-time animation/rendering loop.

```mermaid
flowchart TD
    CLI[User / Command Line] --> MAIN[main.py
CLI parsing and application setup]
    MAIN --> CFG[config.py
AppConfig, modes, ramps, themes]
    CFG --> MAIN

    subgraph Core[Core Processing]
        LOADER[core/image_loader.py
Load and validate image]
        PROCESSOR[core/image_processor.py
Resize, brightness, contrast, gamma, edges]
        CONVERTER[core/ascii_converter.py
Character and pixel-colour conversion]
        ANIMATION[core/animation_engine.py
Seven reveal modes and alpha thresholds]
    end

    MAIN --> LOADER
    LOADER -->|Pillow RGB image| PROCESSOR
    CFG --> PROCESSOR
    PROCESSOR --> CONVERTER
    CFG --> CONVERTER
    CONVERTER -->|AsciiArt data| ANIMATION
    CFG --> ANIMATION

    subgraph Renderer[Pygame Presentation]
        PR[PygameRenderer
Window, event loop, controls]
        TEXT[TextRenderer
Glyph cache and frame compositor]
        COLOR[ColorManager
Themes and web-safe quantisation]
        VIDEO[Video Recorder
60 FPS MP4 output]
    end

    ANIMATION --> PR
    PR --> TEXT
    CFG --> PR
    CFG --> TEXT
    CFG --> COLOR
    TEXT --> COLOR
    PR -->|Screenshot / frame capture| OUTPUT[(output/
Screenshots and MP4 files)]
    PR --> VIDEO
    VIDEO --> OUTPUT

    subgraph Utilities[Shared Utilities]
        HELPERS[utils/helpers.py
Math and dimension helpers]
        VALIDATORS[utils/validators.py
Input and configuration validation]
    end

    MAIN --> VALIDATORS
    CFG --> HELPERS
    ANIMATION --> HELPERS

    ASSETS[(assets/
Source images and fonts)] --> LOADER
    PR --> SCREEN[(Pygame Window
Live artwork and information panel)]
```

## Runtime Flow

```mermaid
sequenceDiagram
    participant U as User
    participant M as main.py
    participant C as Core modules
    participant E as AnimationEngine
    participant R as PygameRenderer

    U->>M: Start with CLI options
    M->>M: Parse arguments and build AppConfig
    M->>C: Load and validate source image
    C->>C: Resize, enhance, and convert to ASCII cells
    C-->>M: AsciiArt data
    M->>E: Create animation engine
    M->>R: Create Pygame renderer
    R->>R: Initialise window, fonts, glyph cache, and compositor

    loop Every frame
        R->>E: Request reveal state using elapsed delta time
        E-->>R: Per-cell visibility alpha values
        R->>R: Composite changed glyphs and apply colour/glow
        R-->>U: Display frame and handle live controls
    end

    opt Video recording or screenshot
        R->>R: Capture the current Pygame frame
        R-->>U: Save output to the output directory
    end
```

## Module Responsibilities

- **`main.py`** — Parses CLI arguments, validates configuration, determines output dimensions, loads the image, and wires the core and renderer together.
- **`config.py`** — Defines `AppConfig`, character ramps, animation modes, and monochrome theme presets.
- **`core/image_loader.py`** — Loads and validates supported image formats.
- **`core/image_processor.py`** — Resizes and adjusts image pixels before ASCII conversion.
- **`core/ascii_converter.py`** — Maps brightness values to characters and extracts source colours.
- **`core/animation_engine.py`** — Implements the seven reveal strategies from normalised per-cell thresholds and delta-time progress.
- **`renderer/pygame_renderer.py`** — Owns the Pygame window, event loop, keyboard controls, UI, glow, screenshots, and video capture.
- **`renderer/text_renderer.py`** — Caches glyph surfaces and incrementally composites only cells that change.
- **`renderer/color_manager.py`** — Resolves themes and quantises original colours for efficient glyph caching.
- **`utils/`** — Provides shared numerical helpers and meaningful input/configuration validation.
