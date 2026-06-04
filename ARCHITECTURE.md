# Architecture

### Understanding Credibility as a User Need
When looking to build a website, users often seek credibility for their business. It is a critical user need in many business cases. 
The diagram below demonstrates the credibility landscape with components. The landing page is the root node here, 
which is that people are seeking landing pages to increase their credibility, and the increasing online presence is part of gaining that credibility.
Also listing Breba and compentitors as providers of the Landing Page components.
```mermaid
wardley-beta
title Breba — Credibility as a User Need

anchor Credibility [0.99, 0.50]

component Professional Landing Page [0.92, 0.5]
component Copywriting [0.65, 0.45]
component Design System [0.80, 0.40]
component Custom Domain [0.25, 0.88]
component Hosting [0.15, 0.92]
component Compute and Storage [0.08, 0.96]

component Figma [0.70, 0.75]
component LLMs [0.58, 0.72]

component LLM Skills [0.65, 0.72]

component Wix [0.85, 0.75]
component Claude Code [0.55, 0.75]
component Breba [0.85, 0.65]

Credibility -> Professional Landing Page
Professional Landing Page -> Copywriting
Professional Landing Page -> Design System
Professional Landing Page -> Wix
Professional Landing Page -> Claude Code
Professional Landing Page -> Breba
Design System -> Figma
Design System -> LLMs

Professional Landing Page -> Custom Domain
Custom Domain -> Hosting
Hosting -> Compute and Storage


evolve Copywriting 0.72
```
