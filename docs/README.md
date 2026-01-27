# Koala Budget Documentation

Welcome to the Koala Budget documentation. This directory contains comprehensive documentation for developers and LLMs working on the project.

## Documentation Index

### Getting Started

| Document | Description | Audience |
|----------|-------------|----------|
| [Getting Started](./getting-started.md) | Setup, commands, and first steps | New developers |
| [Architecture](./architecture.md) | High-level system design | All developers |

### Technical Reference

| Document | Description | Audience |
|----------|-------------|----------|
| [ERD](./erd.md) | Entity Relationship Diagram (Mermaid) | All developers |
| [Data Model](./data-model.md) | Detailed model documentation | Backend developers |
| [API Guide](./api-guide.md) | REST API reference | Full-stack developers |
| [Frontend Guide](./frontend-guide.md) | React/TypeScript patterns | Frontend developers |

### LLM Context

| Document | Description |
|----------|-------------|
| [CLAUDE.md](../context/CLAUDE.md) | Comprehensive context for AI assistants |

### Feature-Specific Documentation

| Document | Description |
|----------|-------------|
| [Reports](./reports.md) | Reports app documentation |
| [Goals Design](./goals_design.md) | Goals feature design document |
| [Actual Tooltip Plan](./actual_tooltip_plan.md) | Budget tooltip implementation plan |

## Quick Links

- **Start developing**: [Getting Started](./getting-started.md)
- **Understand the data**: [ERD](./erd.md) and [Data Model](./data-model.md)
- **Build APIs**: [API Guide](./api-guide.md)
- **Build UI**: [Frontend Guide](./frontend-guide.md)
- **LLM context**: [CLAUDE.md](../context/CLAUDE.md)

## Documentation Levels

The documentation is organized by detail level:

```
High Level (Start Here)
├── README.md (this file)
├── architecture.md - System overview, tech stack, patterns
└── getting-started.md - Setup and common commands

Mid Level (Core Reference)
├── erd.md - Visual database schema
├── api-guide.md - API endpoints and usage
└── frontend-guide.md - Frontend patterns

Low Level (Detailed Reference)
├── data-model.md - Every field of every model
├── reports.md - Specific feature documentation
└── context/CLAUDE.md - Comprehensive LLM context
```

## Keeping Documentation Updated

When making changes:

1. **New models**: Update [ERD](./erd.md) and [Data Model](./data-model.md)
2. **New API endpoints**: Update [API Guide](./api-guide.md)
3. **New frontend patterns**: Update [Frontend Guide](./frontend-guide.md)
4. **Architecture changes**: Update [Architecture](./architecture.md)
5. **LLM context**: Update [CLAUDE.md](../context/CLAUDE.md)

## Viewing Mermaid Diagrams

The ERD uses Mermaid syntax. To view:

1. **GitHub**: Renders automatically
2. **VS Code**: Install "Mermaid Preview" extension
3. **Online**: Paste into [Mermaid Live Editor](https://mermaid.live)
