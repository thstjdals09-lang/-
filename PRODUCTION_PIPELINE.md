# AI Factory — Real Game Studio Production Pipeline

The human user is CEO / Executive Producer. The factory does the work; the user reviews builds and sends revision feedback.

## Production stages

1. **Brief / Theme Intake**
   - Input: theme, genre, platform, constraints
   - Output: project brief

2. **Ideation Room**
   - Creative Director, Game Designer, Systems Designer, Market Research, Producer
   - Multiple concepts are generated and critiqued
   - Output: candidate concepts, critique, selected concept, rejected ideas

3. **Greenlight / Feasibility**
   - Executive Producer, Technical Director, Lead Designer, QA Lead
   - Validate core loop, scope, technical feasibility, risks
   - Gate: GO / REVISE / STOP

4. **Pre-Production**
   - Game Director, Lead Designer, Technical Director, UI/UX, Art Director, Producer
   - GDD, technical architecture, progression, economy, UX flow, art bible, backlog

5. **Playable Prototype**
   - Gameplay Programmer, Systems Programmer, Designer, QA
   - Build the smallest playable version that proves the core loop

6. **Vertical Slice**
   - Gameplay, UI, Art, Audio, QA, Technical Art, Producer
   - One small section at near-final quality
   - Defines the quality bar for production

7. **Full Production**
   - Feature teams implement gameplay, systems, content, UI, save/load, tools, art, audio
   - Continuous integration and playable builds

8. **Internal QA / Integration**
   - Functional QA, regression, compatibility, performance, save migration, crash testing

9. **Alpha**
   - Feature complete target
   - Stabilization and missing-content closure

10. **Beta**
    - Content complete target
    - Balance, performance, compatibility and release-candidate work

11. **Polish / Certification**
    - UX polish, accessibility, localization, store requirements, platform checks

12. **Release Build**
    - Signed build / distributable artifact
    - Release notes and version tag

13. **Live Operations**
    - Crash/feedback monitoring, patches, content updates, experiments

## Factory behavior

- The router assigns AI employees by role, capability, quota and availability.
- Every stage produces reviewable artifacts.
- Stage gates can automatically continue when quality thresholds pass.
- The CEO can stop the line, approve, reject, or request revisions at any time.
- GitHub is the default source-of-truth repository for code and production artifacts.
