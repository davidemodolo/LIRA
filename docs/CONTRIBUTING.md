# Contributing to L.I.R.A.

Thank you for your interest in contributing to L.I.R.A.!

## Development Setup

### Prerequisites
- Python 3.10+
- uv package manager
- Git

### Getting Started

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/lira.git
   cd lira
   ```

2. **Install dependencies**
   ```bash
   uv sync --dev
   ```

3. **Install pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

4. **Run the development server**
   ```bash
   uv run fastapi dev src/lira/api/main.py
   ```

5. **Run tests**
   ```bash
   uv run pytest
   ```

## Code Style

### Formatting
- We use Ruff formatter (Black-compatible)
- 100 character line length
- Single quotes for strings (unless escaping)

```bash
# Format code
uv run ruff format src/

# Check formatting
uv run ruff format --check src/
```

### Linting
- Ruff for linting with strict rules
- No unused imports
- Type hints required for public APIs

```bash
# Lint code
uv run ruff check src/

# Auto-fix issues
uv run ruff check --fix src/
```

### Type Checking
- MyPy for type checking
- Pydantic v2 plugin enabled
- No `Any` types in public APIs

```bash
# Type check
uv run mypy src/
```

## Testing

### Test Organization
- Unit tests: `tests/unit/`
- Integration tests: `tests/integration/`
- Test fixtures: `tests/conftest.py`

### Writing Tests
```python
def test_feature_description(session, sample_data):
    """Test description of what is being tested."""
    # Arrange
    expected = create_expected_state()
    
    # Act
    result = perform_action()
    
    # Assert
    assert result == expected
```

### Running Tests
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=lira --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_agent.py

# Run with markers
uv run pytest -m "not slow"
```

## Commit Guidelines

### Commit Message Format
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, no code change
- `refactor`: Code restructuring
- `test`: Adding tests
- `chore`: Maintenance tasks

### Examples
```bash
git commit -m "feat(api): add transaction query endpoint"
git commit -m "fix(portfolio): correct cost basis calculation"
git commit -m "docs: update ARCHITECTURE.md with new module"
```

## Pull Request Process

1. **Create a branch**
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes**
   - Follow code style guidelines
   - Add/update tests
   - Update documentation if needed

3. **Run quality checks**
   ```bash
   uv run ruff check src/
   uv run ruff format src/
   uv run mypy src/
   uv run pytest
   ```

4. **Push and create PR**
   ```bash
   git push origin feature/my-feature
   ```

5. **PR Description should include**
   - Summary of changes
   - Related issue numbers
   - Testing performed
   - Any breaking changes

## Project Structure

```
LIRA/
├── src/lira/           # Main package
│   ├── core/          # Agentic loop
│   ├── db/            # Database layer
│   ├── mcp/           # MCP server
│   ├── api/           # REST API
│   ├── cli/           # CLI interface
│   └── services/      # Business logic
├── tests/             # Test suite
├── docs/              # Documentation
├── pyproject.toml     # Project config
└── README.md          # Project overview
```

## Issue Guidelines

### Bug Reports
- Include Python version
- Include full traceback
- Include minimal reproduction case
- Describe expected vs actual behavior

### Feature Requests
- Describe the use case
- Explain why it would be valuable
- Provide example usage
- Consider backward compatibility

## Questions?

- Open an issue for bugs/questions
- Check existing issues before creating new ones
- Be respectful and constructive in discussions

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
