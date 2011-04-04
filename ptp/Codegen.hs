{-
    Copyright (C) 2010,2011 Stanislav Bohm

    This file is part of Kaira.

    Kaira is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, version 3 of the License, or
    (at your option) any later version.

    Kaira is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Kaira.  If not, see <http://www.gnu.org/licenses/>.
-}

module Codegen (
	emitProgram,
	typeString,
	typeSafeString,
	orderTypeByDepedancy -- for Tests.hs
) where

import qualified Data.Map as Map
import qualified Data.Set as Set
import qualified Data.List as List
import Declarations
import CodegenTypes
import Utils
import ProjectTools
import CodegenTools

data Scope = Scope {
	scopeDeclarations :: Declarations
} deriving (Show)

data SourceCode = Text String
	| Join SourceCode SourceCode
	| Block SourceCode
	| Eol
	| LineDirective (Maybe (String, Int)) -- Nothing means "return to original source file"
	| Empty

stdFunctions = [
	("+", TInt, [TInt, TInt]),
	("*", TInt, [TInt, TInt]),
	("-", TInt, [TInt, TInt]),
	("%", TInt, [TInt, TInt]),
	("/", TInt, [TInt, TInt]),
	(".iid", TInt, []) ]

(<+>) :: SourceCode -> SourceCode -> SourceCode
a <+> Empty = a
Empty <+> b = b
a <+> b = Join a b

indentStr :: Int -> String
indentStr n = List.replicate n '\t'

joinMap :: (a -> SourceCode) -> [a] -> SourceCode
joinMap f = foldr ((<+>) . f) Empty

infixFunctions = [ "+", "-", "/", "*", "!=", "==", "||", "&&", ">=", "<=", ">", "<", "%" ]

addDeclarations :: Scope -> Declarations -> Scope
addDeclarations scope decls =
	Scope $ decls `declarationsJoin` scopeDeclarations scope

emitCall scope ('.':name) (obj:params) =
	emitExpression scope obj ++ dotOrArrow ++ name ++ "(" ++ addDelimiter "," (map (emitExpression scope) params) ++ ")"
	where dotOrArrow =
		case exprType (scopeDeclarations scope) obj of
			TStruct _ _ -> "."
			TPointer _ -> "->"
			TRaw _ -> "."
			TString -> "."
			TPlace _ -> "."
			x -> error $ "Invalid type for calling method '" ++ name ++ "' at " ++ show obj ++ "/" ++ show x

emitCall scope "Base.asString" [x] = emitExpression scope $ exprAsString (scopeDeclarations scope) x
emitCall scope "List.size" [e1] = emitExpression scope e1 ++ ".size()"
emitCall scope "List.clear" [e1] = emitExpression scope e1 ++ ".clear()"
emitCall scope "List.eraseAt" [e1,e2] =
	emitExpression scope e1 ++ ".erase(" ++ emitExpression scope e1 ++ ".begin()+" ++ emitExpression scope e2 ++ ")"
emitCall scope "List.append" [e1,e2] =
	emitExpression scope e1 ++ ".push_back(" ++ emitExpression scope e2 ++ ")"
emitCall scope name [e1] | name `elem` infixFunctions = 	emitExpression scope e1
emitCall scope name (e:rest) | name `elem` infixFunctions =
	"(" ++ emitExpression scope e ++ " " ++ name ++ " " ++ emitCall scope name rest ++ ")"
emitCall scope name params =
	name ++ "(" ++ addDelimiter "," (map (emitExpression scope) params) ++ ")"

emitExpression :: Scope -> Expression -> String
emitExpression scope (EVar s) = s
emitExpression scope (EType s) = s
emitExpression scope (EInt i) = show i
emitExpression scope (EString str) = "\"" ++ escapeString str ++ "\""
emitExpression scope (ECall name params) = emitCall scope name params
emitExpression scope (ECast e t) = "((" ++ typeString t ++ ") " ++ emitExpression scope e ++ ")"
{- Tuple at -}
emitExpression scope (EAt (EInt index) expr) =
	case exprType (scopeDeclarations scope) expr of
		TTuple _ -> emitExpression scope expr ++ "." ++ emitTupleMember index
		TPointer (TTuple _) -> emitExpression scope expr ++ "->" ++ emitTupleMember index
		t -> error $ "Unsuported type in emitExpression (EAt): " ++ show index ++ " " ++ show expr ++ "/" ++ show t

emitExpression scope (EAt (EString index) expr) =
	case exprType (scopeDeclarations scope) expr of
		TStruct _ _ -> emitExpression scope expr ++ "." ++ index
		TPointer _ -> emitExpression scope expr ++ "->" ++ index
		x -> error $ "Unsuported type in emitExpression (EAt): " ++ show index

emitExpression scope (EAddr expr) = "&(" ++ emitExpression scope expr ++ ")"
emitExpression scope (EDeref expr) = "*(" ++ emitExpression scope expr ++ ")"
emitExpression scope x = error $ "EmitExpression: " ++ show x

emitVarDeclarations :: Scope -> [VarDeclaration] -> SourceCode
emitVarDeclarations scope vdecls =
	joinMap declare vdecls
	where
		declare (name, t) = Text (typeString t ++ " " ++ name ++ ";") <+> Eol

emitInstruction :: Scope -> Instruction -> SourceCode
emitInstruction scope (IExpr expr) = Text (emitExpression scope expr ++ ";") <+> Eol
emitInstruction scope (ISet expr1 expr2) =
	Text (emitExpression scope expr1 ++ " = " ++ emitExpression scope expr2 ++ ";") <+> Eol
emitInstruction scope (IStatement decls instructions) =
	Text "{" <+> Block (declarationsCode <+> instructionsCode) <+> Text "}" <+> Eol
	where
		instructionsCode = joinMap (emitInstruction newScope) instructions
		newScope = addDeclarations scope (statementDeclarations decls instructions)
		declarationsCode = emitVarDeclarations newScope decls
emitInstruction scope (IDefine name t (Just expr)) =
	Text (typeString t ++ " " ++ name ++ " = " ++ emitExpression scope expr ++ ";") <+> Eol
emitInstruction scope (IDefine name t Nothing) =
	Text (typeString t ++ " " ++ name ++ ";") <+> Eol
emitInstruction scope (IReturn expr) = Text ("return " ++ emitExpression scope expr ++ ";") <+> Eol
emitInstruction scope IContinue = Text "continue;" <+> Eol
emitInstruction scope INoop = Empty
emitInstruction scope (IForeach var counterVar expr body) =
	Text ("for (" ++ varDecl ++ "; " ++ cycleTest ++ "; " ++ counterVar ++ "++) {")
	<+> Block (setVar <+> joinMap emit body) <+> Text "}" <+> Eol
	where
		elementType = case exprType (scopeDeclarations scope) expr  of
						TArray t -> t
						TPlace t -> t
						_ -> error "Unsuported type for IForeach"
		arrayLen = "(" ++ emitExpression scope expr ++ ").size()"
		setVar = Text (typeString elementType ++ " " ++ var ++ " = " ++ emitExpression scope expr ++ "[" ++ counterVar ++ "];") <+> Eol
		varDecl = "size_t " ++ counterVar ++ " = 0"
		cycleTest = counterVar ++ " < " ++ arrayLen
		emit = emitInstruction
			(addDeclarations scope (makeDeclarations [ (counterVar, TInt), (var, elementType) ] []))
emitInstruction scope (IInline str) = Text str <+> Eol
emitInstruction scope (IIf expr branch1 INoop) =
	Text ("if (" ++ emitExpression scope expr ++ ") ") <+> emitInstruction scope branch1
emitInstruction scope (IIf expr branch1 branch2) =
	Text ("if (" ++ emitExpression scope expr ++ ") ") <+> emitInstruction scope branch1 <+> Text "else " <+> emitInstruction scope branch2
emitTupleMember index = "t_" ++ show index

-- initialScope :: Function -> Declaration -> Scope
-- initialScope function fundecls = Scope { scopeDeclarations = decls }
--where decls = makeDeclarations (varFromParam (parameters function) ++ declarations function) fundecls

typeString :: Type -> String
typeString (TArray t) = "std::vector<" ++ typeString t ++ " >"
typeString (TPlace t) = "CaPlace<" ++ typeString t ++ " >"
typeString (TRaw d) = d
typeString (TPointer t) = typeString t ++ "*"
typeString (TStruct name _) = name
typeString TString = "std::string"
typeString TBool = "bool"
typeString (TData _ rawType _ _) = rawType
typeString x = typeSafeString x

-- |Converts type to string in way that string can be used as part of identifier
typeSafeString :: Type -> String
typeSafeString TVoid = "void"
typeSafeString TInt = "int"
typeSafeString TFloat = "float"
typeSafeString TDouble = "double"
typeSafeString TString = "string"
typeSafeString (TPlace t) = "place_" ++ typeSafeString t
typeSafeString TBool = "bool"
typeSafeString (TTuple ts) = "Tuple" ++ show (length ts) ++ "_" ++ addDelimiter "_" (map typeSafeString ts)
typeSafeString TUndefined = "<undefined>"
typeSafeString (TArray t) = "Array_" ++ typeSafeString t
typeSafeString (TRaw d) = d
typeSafeString (TPointer t) = "Ptr_" ++ typeSafeString t
typeSafeString (TStruct name _) = name
typeSafeString (TData name _ _ _) = name
--typeSafeString x = error $ "typeSafeString: " ++ show x

declareVar :: Scope -> String -> String
declareVar scope varName =
	case varType (scopeDeclarations scope) varName of
		TUndefined -> error "Undefined variable cannot be defined"
		t -> typeString t ++ " " ++ varName

declareVar' :: [VarDeclaration] -> [String]
declareVar' [] = []
declareVar' ((name,t):vs) = (typeString t ++ " " ++ name) : declareVar' vs

declareParam :: [ParamDeclaration] -> [String]
declareParam [] = []
declareParam ((name,(TPointer t), _):vs) = (typeString t ++ "* " ++ name) : declareParam vs
declareParam ((name,(TRaw d), _):vs) = (d ++ " " ++ name) : declareParam vs
declareParam ((name,t, ptype):vs)
	| t == TInt = (typeString t ++ " " ++ name) : declareParam vs
	| t == TString || ptype == ParamConst = ("const " ++ typeString t ++ " & " ++ name) : declareParam vs
	| otherwise = (typeString t ++ " & " ++ name) : declareParam vs

emitFunction :: [FunDeclaration] -> Function -> SourceCode
emitFunction fundecls function =
	prefix <+> Text functionDeclaration <+> Eol <+> body <+> suffix
	where
		functionDeclaration = typeString (returnType function) ++ " " ++ functionName function ++ "(" ++ paramString ++ ")"
		decls = makeDeclarations (varFromParam (parameters function) ++ statementVarList (instructions function)) fundecls
		body = emitInstruction scope (addConstructors decls statement)
		scope = Scope { scopeDeclarations = decls }
		paramString = addDelimiter "," $ declareParam (parameters function)
		statement = makeStatement [] (instructions function ++ extraInstructions)
		(prefix, suffix) = case functionSource function of
				Just x -> (LineDirective (Just x), LineDirective Nothing)
				Nothing -> (Empty, Empty)
		extraInstructions = case extraCode function of
				"" -> [INoop]
				x -> [IInline x]

emitGlobals :: [VarDeclaration] -> String
emitGlobals [] = ""
emitGlobals ((name, t):rest) =
	typeString t ++ " " ++ name ++ ";\n" ++ emitGlobals rest

orderTypeByDepedancy :: (Set.Set Type) -> [Type]
orderTypeByDepedancy types =
	dependacyOrder orderFn types
	where
		orderFn ordered t = Set.empty == Set.difference (subTypes t) (Set.fromList ordered)

makeFunctionDeclaration :: Function -> FunDeclaration
makeFunctionDeclaration function = (functionName function, returnType function, [ t | (_, t, _) <- parameters function ])

emitProgram :: String -> String -> [VarDeclaration] -> [Function] -> String
emitProgram fileName prologue globals functions =
	sourceCodeToStr fileName $
	Text prologue <+> typeDeclarations <+> Text (emitGlobals globals) <+> Eol <+> joinMap (emitFunction fundecls) functions
	where
		typeDeclarations = Text $ concatMap emitTypeDeclaration orderedTypes
		allTypes = Set.fold (\t s -> Set.union s $ subTypes' t) Set.empty (Set.unions (map gatherTypes functions))
		allDefinedTypes = Set.filter isDefined allTypes
		orderedTypes = orderTypeByDepedancy allDefinedTypes
		fundecls = map makeFunctionDeclaration functions ++ stdFunctions

emitTypeDeclaration :: Type -> String
emitTypeDeclaration (TTuple types) =
	emitTypeDeclaration (TStruct name decls)
	where
		name = typeSafeString (TTuple types)
		decls = zip (map (\x -> "t_" ++ show x) [0..]) types

emitTypeDeclaration (TStruct name decls) =
	"struct " ++ name ++ " {\n" ++ constructor1 ++ "\n" ++ constructor2 ++ innerPart decls ++ "};\n"
	where
		innerPart [] = ""
		innerPart ((name, t):ts) = "\t" ++ typeString t ++ " " ++ name ++ ";\n" ++ innerPart ts
		constructor1 = "\t" ++ name ++ "() {}"
		constructor2
			| decls == [] = ""
			| otherwise = "\t" ++ name ++ "(" ++ addDelimiter "," (map (\(n,t) -> const t ++ typeString t ++ " & " ++ n) decls) ++ ") {\n"
				++ concatMap (\(n,t) -> "\t\tthis->" ++ n ++ " = " ++ n ++ ";\n") decls ++ "\t}\n"
		const t = case t of
			(TData _ _ _ _) -> ""
			(TPointer _) -> ""
			_ -> "const "

emitTypeDeclaration _ = ""

varDeclarationTypes :: [VarDeclaration] -> TypeSet
varDeclarationTypes decls = Set.fromList [ t | (n,t) <- decls ]

paramDeclarationTypes :: [ParamDeclaration] -> TypeSet
paramDeclarationTypes decls = Set.fromList [ t | (n,t,_) <- decls ]

gatherExprTypes :: Expression -> TypeSet
gatherExprTypes x =
	case exprType emptyDeclarations x of -- FIXME: not emptyDeclarations
		TUndefined -> Set.empty
		t -> Set.singleton t

gatherInstructionTypes :: Instruction -> TypeSet
gatherInstructionTypes (IExpr expr) = gatherExprTypes expr
gatherInstructionTypes (ISet _ expr) = gatherExprTypes expr
gatherInstructionTypes (IIf expr i1 i2) =
	Set.unions [ gatherExprTypes expr, gatherInstructionTypes i1, gatherInstructionTypes i2 ]
gatherInstructionTypes (IStatement decls instrs) =
	Set.union (varDeclarationTypes decls) $ Set.unions (map gatherInstructionTypes instrs)
gatherInstructionTypes (IForeach _ _ expr instrs) =
	Set.union (gatherExprTypes expr) $ Set.unions (map gatherInstructionTypes instrs)
gatherInstructionTypes (IDefine _ t (Just expr)) = Set.union (Set.singleton t) (gatherExprTypes expr)
gatherInstructionTypes (IDefine _ t Nothing) = Set.singleton t
gatherInstructionTypes INoop = Set.empty
gatherInstructionTypes _ = Set.empty

gatherTypes :: Function -> TypeSet
gatherTypes f =
	Set.unions $ [ paramDeclarationTypes (parameters f)] ++ map gatherInstructionTypes (instructions f)

{-
	subTypes' x returns subtypes with x
 	subTypes x returns subtypes without x
-}

subTypes :: Type -> TypeSet
subTypes (TArray t) = subTypes' t
subTypes (TPlace t) = subTypes' t
subTypes (TTuple types) = Set.unions $ map subTypes' types
subTypes (TPointer t) = subTypes' t
subTypes (TStruct _ decls) = Set.unions $ map (subTypes'.snd) decls
subTypes _ = Set.empty

subTypes' :: Type -> TypeSet
subTypes' tt = Set.union (Set.singleton tt) (case tt of
	(TArray t) -> subTypes' t
	(TPlace t) -> subTypes' t
	(TTuple types) -> Set.unions $ map subTypes' types
	(TPointer t) -> subTypes' t
	(TStruct name decls) -> Set.unions $ map (subTypes'.snd) decls
	_ -> Set.empty)

addConstructors :: Declarations -> Instruction -> Instruction
addConstructors decls i =
	mapExprs' addConstr decls i
	where
       addConstr decls (ETuple xs) =
			let t = (exprType decls (ETuple xs)) in
				ECast (ECall (typeSafeString t) $ map (addConstr decls) xs) t

       addConstr decls (ECall name exprs) = ECall name $ map (addConstr decls) exprs
       addConstr decls (EAt a b) = EAt (addConstr decls a) (addConstr decls b)
       addConstr decls (EDeref e) = EDeref $ addConstr decls e
       addConstr decls (EAddr e) = EAddr $ addConstr decls e
       addConstr decls x = x

exprAsString :: Declarations -> Expression -> Expression
exprAsString decls (EString x) = EString x
exprAsString decls (EInt x) = EString $ show x
exprAsString decls x =
	case exprType decls x of
		TInt -> ECall "ca_int_to_string" [x]
		TFloat -> ECall "ca_float_to_string" [x]
		TDouble -> ECall "ca_double_to_string" [x]
		TString -> x
		TTuple [] -> EString "()"
		(TData name _ _ functions) | hasKey "getstring" functions -> ECall (name ++ "_getstring") [x]
		(TData name _ _ _) -> ECall "std::string" [ EString name ]
		TTuple types -> ECall "+" $ [ ECall "std::string"
			[ EString "(" ], ECall "Base.asString" [ EAt (EInt 0) x ]]
				++ concat [ [EString ",", ECall "Base.asString"
					[ EAt (EInt i) x ]] | i <- [1..length types-1]] ++ [ EString ")" ]
		t -> error $ "exprAsString: " ++ show x ++ "/" ++ show t

sourceCodeToStr :: String -> SourceCode -> String
sourceCodeToStr originalFilename code =
	let (str, l) = toStr code 0 True 1 in str
	where
		toStr :: SourceCode -> Int -> Bool -> Int -> (String, Int)
		toStr (Join a b) n i lineno =
			let (str1, l1) = toStr a n i lineno in
			let	(str2, l2) = toStr b n (endWithEol a) l1 in
					(str1 ++ str2, l2)
		toStr (Text s) n True lineno = (indentStr n ++ s, lineno + countOfEols s)
		toStr (Text s) _ False lineno = (s, lineno + countOfEols s)
		toStr (Block c) n i lineno = let (str, l) = toStr c (n + 1) True (lineno + 1) in
			("\n" ++ str ++ end, l + lineno')
			where (end, lineno') = if endWithEol c then ("",0) else ("\n", 1)
		toStr Eol _ _ lineno = ("\n", lineno + 1)
		toStr (LineDirective (Just (file, lnum))) _ _ lineno =
			("#line " ++ show lnum ++ " \"" ++ file ++ "\"\n", lineno + 1)
		toStr (LineDirective Nothing) _ _ lineno =
			("#line " ++ show (lineno + 1) ++ " \"" ++ originalFilename ++ "\"\n", lineno + 1)
		toStr Empty _ _ lineno = ("",lineno)

		endWithEol Eol = True
		endWithEol (Text str) = "\n" `List.isSuffixOf` str
		endWithEol (Block _) = True
		endWithEol (LineDirective _) = True
		endWithEol (Join a b) = endWithEol b
		endWithEol _ = False

		countOfEols [] = 0
		countOfEols ('\n':xs) = 1 + countOfEols xs
		countOfEols (_:xs) = countOfEols xs
