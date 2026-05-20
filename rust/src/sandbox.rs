//! 安全沙箱 — 安全数学表达式求值器
//!
//! 对应 Python: core/sandbox.py (safe_calculator)
//!
//! 仅支持安全操作：+ - * / % ** 和基本函数，无文件/网络访问

use pyo3::prelude::*;
use std::collections::HashMap;
use std::time::{Duration, Instant};

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SandboxExecutor>()?;
    Ok(())
}

/// 安全数学表达式求值器
/// 支持: + - * / % **, sqrt, abs, min, max, sin, cos, log, floor, ceil, round
#[pyclass]
pub struct SandboxExecutor {
    timeout_ms: u64,
}

#[pymethods]
impl SandboxExecutor {
    #[new]
    fn new(timeout_ms: Option<u64>) -> Self {
        SandboxExecutor {
            timeout_ms: timeout_ms.unwrap_or(5000),
        }
    }

    fn safe_eval(&self, expression: &str) -> PyResult<f64> {
        let start = Instant::now();
        let result = self.eval_inner(expression, start);
        result.map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
    }

    fn health(&self) -> &'static str {
        "sandbox: operational (safe math eval)"
    }
}

#[derive(Debug)]
enum Token {
    Number(f64),
    Plus,
    Minus,
    Mul,
    Div,
    Mod,
    Pow,
    LParen,
    RParen,
    Comma,
    Ident(String),
}

struct Tokenizer {
    chars: Vec<char>,
    pos: usize,
}

impl Tokenizer {
    fn new(input: &str) -> Self {
        Tokenizer {
            chars: input.chars().collect(),
            pos: 0,
        }
    }

    fn tokenize(&mut self) -> Result<Vec<Token>, String> {
        let mut tokens = Vec::new();
        while self.pos < self.chars.len() {
            let ch = self.chars[self.pos];
            match ch {
                ' ' | '\t' | '\n' | '\r' => { self.pos += 1; }
                '+' => { tokens.push(Token::Plus); self.pos += 1; }
                '-' => {
                    // Check if unary minus
                    if tokens.is_empty() || matches!(tokens.last().unwrap(),
                        Token::Plus | Token::Minus | Token::Mul | Token::Div | Token::Mod |
                        Token::Pow | Token::LParen | Token::Comma)
                    {
                        tokens.push(Token::Number(-1.0));
                        tokens.push(Token::Mul);
                    } else {
                        tokens.push(Token::Minus);
                    }
                    self.pos += 1;
                }
                '*' => {
                    self.pos += 1;
                    if self.pos < self.chars.len() && self.chars[self.pos] == '*' {
                        tokens.push(Token::Pow);
                        self.pos += 1;
                    } else {
                        tokens.push(Token::Mul);
                    }
                }
                '/' => { tokens.push(Token::Div); self.pos += 1; }
                '%' => { tokens.push(Token::Mod); self.pos += 1; }
                '(' => { tokens.push(Token::LParen); self.pos += 1; }
                ')' => { tokens.push(Token::RParen); self.pos += 1; }
                ',' => { tokens.push(Token::Comma); self.pos += 1; }
                '0'..='9' | '.' => {
                    let start = self.pos;
                    while self.pos < self.chars.len() &&
                        (self.chars[self.pos].is_ascii_digit() || self.chars[self.pos] == '.') {
                        self.pos += 1;
                    }
                    let num_str: String = self.chars[start..self.pos].iter().collect();
                    let num = num_str.parse::<f64>()
                        .map_err(|_| format!("Invalid number: {}", num_str))?;
                    tokens.push(Token::Number(num));
                }
                'a'..='z' | 'A'..='Z' | '_' => {
                    let start = self.pos;
                    while self.pos < self.chars.len() &&
                        (self.chars[self.pos].is_alphanumeric() || self.chars[self.pos] == '_') {
                        self.pos += 1;
                    }
                    let ident: String = self.chars[start..self.pos].iter().collect();
                    tokens.push(Token::Ident(ident));
                }
                _ => return Err(format!("Unexpected character: '{}'", ch)),
            }
        }
        Ok(tokens)
    }
}

struct Parser {
    tokens: Vec<Token>,
    pos: usize,
    functions: HashMap<String, fn(f64) -> f64>,
}

impl Parser {
    fn new(tokens: Vec<Token>) -> Self {
        let mut functions: HashMap<String, fn(f64) -> f64> = HashMap::new();
        functions.insert("sqrt".to_string(), f64::sqrt);
        functions.insert("abs".to_string(), |x| x.abs());
        functions.insert("sin".to_string(), f64::sin);
        functions.insert("cos".to_string(), f64::cos);
        functions.insert("log".to_string(), f64::ln);
        functions.insert("exp".to_string(), f64::exp);
        functions.insert("floor".to_string(), f64::floor);
        functions.insert("ceil".to_string(), f64::ceil);
        functions.insert("round".to_string(), f64::round);
        Parser { tokens, pos: 0, functions }
    }

    fn peek(&self) -> Option<&Token> {
        self.tokens.get(self.pos)
    }

    fn advance(&mut self) -> Option<&Token> {
        let t = self.tokens.get(self.pos);
        self.pos += 1;
        t
    }

    fn parse_expression(&mut self) -> Result<f64, String> {
        self.parse_add_sub()
    }

    fn parse_add_sub(&mut self) -> Result<f64, String> {
        let mut left = self.parse_mul_div_mod()?;
        loop {
            match self.peek() {
                Some(Token::Plus) => { self.advance(); left += self.parse_mul_div_mod()?; }
                Some(Token::Minus) => { self.advance(); left -= self.parse_mul_div_mod()?; }
                _ => break,
            }
        }
        Ok(left)
    }

    fn parse_mul_div_mod(&mut self) -> Result<f64, String> {
        let mut left = self.parse_power()?;
        loop {
            match self.peek() {
                Some(Token::Mul) => { self.advance(); left *= self.parse_power()?; }
                Some(Token::Div) => {
                    self.advance();
                    let right = self.parse_power()?;
                    if right == 0.0 { return Err("Division by zero".to_string()); }
                    left /= right;
                }
                Some(Token::Mod) => {
                    self.advance();
                    let right = self.parse_power()?;
                    if right == 0.0 { return Err("Modulo by zero".to_string()); }
                    left %= right;
                }
                _ => break,
            }
        }
        Ok(left)
    }

    fn parse_power(&mut self) -> Result<f64, String> {
        let base = self.parse_unary()?;
        if matches!(self.peek(), Some(Token::Pow)) {
            self.advance();
            let exp = self.parse_power()?;
            return Ok(base.powf(exp));
        }
        Ok(base)
    }

    fn parse_unary(&mut self) -> Result<f64, String> {
        self.parse_atom()
    }

    fn parse_atom(&mut self) -> Result<f64, String> {
        match self.advance() {
            Some(Token::Number(n)) => Ok(*n),
            Some(Token::LParen) => {
                let result = self.parse_expression()?;
                match self.advance() {
                    Some(Token::RParen) => Ok(result),
                    _ => Err("Expected ')'".to_string()),
                }
            }
            Some(Token::Ident(name)) => {
                let name = name.clone();
                // function call with args
                if matches!(self.peek(), Some(Token::LParen)) {
                    self.advance(); // consume '('
                    let mut args = Vec::new();
                    if !matches!(self.peek(), Some(Token::RParen)) {
                        args.push(self.parse_expression()?);
                        while matches!(self.peek(), Some(Token::Comma)) {
                            self.advance();
                            args.push(self.parse_expression()?);
                        }
                    }
                    match self.advance() {
                        Some(Token::RParen) => {}
                        _ => return Err("Expected ')' after function args".to_string()),
                    }

                    match name.as_str() {
                        "min" => {
                            if args.len() < 2 { return Err("min() requires 2+ args".to_string()); }
                            Ok(args.iter().copied().fold(f64::INFINITY, f64::min))
                        }
                        "max" => {
                            if args.len() < 2 { return Err("max() requires 2+ args".to_string()); }
                            Ok(args.iter().copied().fold(f64::NEG_INFINITY, f64::max))
                        }
                        "pi" if args.is_empty() => Ok(std::f64::consts::PI),
                        "e" if args.is_empty() => Ok(std::f64::consts::E),
                        _ => {
                            if args.len() != 1 {
                                return Err(format!("Function '{}' requires exactly 1 argument", name));
                            }
                            match self.functions.get(&name) {
                                Some(f) => Ok(f(args[0])),
                                None => Err(format!("Unknown function: {}", name)),
                            }
                        }
                    }
                } else {
                    // constant
                    match name.as_str() {
                        "pi" => Ok(std::f64::consts::PI),
                        "e" => Ok(std::f64::consts::E),
                        _ => Err(format!("Unknown identifier: {}", name)),
                    }
                }
            }
            Some(tok) => Err(format!("Unexpected token: {:?}", tok)),
            None => Err("Unexpected end of expression".to_string()),
        }
    }
}

impl SandboxExecutor {
    fn eval_inner(&self, expression: &str, start: Instant) -> Result<f64, String> {
        if expression.len() > 2000 {
            return Err("Expression too long (max 2000 chars)".to_string());
        }

        let mut tokenizer = Tokenizer::new(expression);
        let tokens = tokenizer.tokenize()?;

        // timeout check
        if start.elapsed() > Duration::from_millis(self.timeout_ms) {
            return Err("Evaluation timed out".to_string());
        }

        let mut parser = Parser::new(tokens);
        let result = parser.parse_expression()?;

        if start.elapsed() > Duration::from_millis(self.timeout_ms) {
            return Err("Evaluation timed out".to_string());
        }

        if result.is_infinite() || result.is_nan() {
            return Err("Result is not a finite number".to_string());
        }

        Ok(result)
    }
}
