#  Swift Demangler

import re

class SwiftDemangler:
    def __init__(self, symbol):
        self.raw = symbol
        self.ptr = 0
        self.length = len(symbol)
        self.components = []
        self.kind = "Unknown"
        self.access = "default"
        self.detailed_info = []

    def demangle(self):
        # 1. Check Prefix
        if self.raw.startswith('_$s'):
            self.ptr = 3
        elif self.raw.startswith('$s'):
            self.ptr = 2
        else:
            return None # Not a Swift 5+ symbol

        try:
            self._parse_sequence()
            return self._format_result()
        except Exception:
            return None

    def _format_result(self):
        # Construct the "Demangled Name"
        name_path = ".".join(self.components)
        
        # Construct the detailed description
        details = f"demangled name = {name_path}"
        
        if self.kind:
            details += f", type = {self.kind}"
        
        # Add specific flags found during parsing
        if self.detailed_info:
            info_str = ", ".join(self.detailed_info)
            details += f" ({info_str})"
            
        return details

    def _peek(self):
        if self.ptr < self.length:
            return self.raw[self.ptr]
        return None

    def _next(self):
        c = self._peek()
        if c: self.ptr += 1
        return c

    def _read_int(self):
        # Reads digits until a non-digit is found
        num_str = ""
        while self.ptr < self.length and self.raw[self.ptr].isdigit():
            num_str += self.raw[self.ptr]
            self.ptr += 1
        return int(num_str) if num_str else 0

    def _parse_identifier(self):
        # Identifiers are Length + String (e.g., "6MailUI")
        if self.ptr >= self.length or not self.raw[self.ptr].isdigit():
            return None
        
        length = self._read_int()
        if self.ptr + length > self.length:
            return None
            
        ident = self.raw[self.ptr : self.ptr + length]
        self.ptr += length
        return ident

    def _parse_known_type(self, char):
        # Mapping common Swift Standard Library short codes
        # See: https://github.com/swiftlang/swift/blob/main/include/swift/Demangling/StandardTypesMangling.def
        
        # 1. Standard Substitutions (derived from STANDARD_TYPE macros)
        # These are used when the parser encounters 'S' followed by one of these chars.
        standard_types = {
            'A': 'AutoreleasingUnsafeMutablePointer',
            'a': 'Array',
            'b': 'Bool',
            'D': 'Dictionary',
            'd': 'Double',
            'f': 'Float',
            'h': 'Set',
            'I': 'DefaultIndices',
            'i': 'Int',
            'J': 'Character',
            'N': 'ClosedRange',
            'n': 'Range',
            'O': 'ObjectIdentifier',
            'P': 'UnsafePointer',
            'p': 'UnsafeMutablePointer',
            'R': 'UnsafeBufferPointer',
            'r': 'UnsafeMutableBufferPointer',
            'S': 'String',
            's': 'Substring',
            'u': 'UInt',
            'V': 'UnsafeRawPointer',
            'v': 'UnsafeMutableRawPointer',
            'W': 'UnsafeRawBufferPointer',
            'w': 'UnsafeMutableRawBufferPointer',
            'q': 'Optional',
            'B': 'BinaryFloatingPoint',
            'E': 'Encodable',
            'e': 'Decodable',
            'F': 'FloatingPoint',
            'G': 'RandomNumberGenerator',
            'H': 'Hashable',
            'j': 'Numeric',
            'K': 'BidirectionalCollection',
            'k': 'RandomAccessCollection',
            'L': 'Comparable',
            'l': 'Collection',
            'M': 'MutableCollection',
            'm': 'RangeReplaceableCollection',
            'Q': 'Equatable',
            'T': 'Sequence',
            't': 'IteratorProtocol',
            'U': 'UnsignedInteger',
            'X': 'RangeExpression',
            'x': 'Strideable',
            'Y': 'RawRepresentable',
            'y': 'StringProtocol',
            'Z': 'SignedInteger',
            'z': 'BinaryInteger'
        }

        # 2. Concurrency Substitutions (derived from STANDARD_TYPE_CONCURRENCY macros)
        # These are used when the parser encounters 'Sc' followed by one of these chars.
        concurrency_types = {
            'A': 'Actor',
            'C': 'CheckedContinuation',
            'c': 'UnsafeContinuation',
            'E': 'CancellationError',
            'e': 'UnownedSerialExecutor',
            'F': 'Executor',
            'f': 'SerialExecutor',
            'G': 'TaskGroup',
            'g': 'ThrowingTaskGroup',
            'h': 'TaskExecutor',
            'I': 'AsyncIteratorProtocol',
            'i': 'AsyncSequence',
            'J': 'UnownedJob',
            'M': 'MainActor',
            'P': 'TaskPriority',
            'S': 'AsyncStream',
            's': 'AsyncThrowingStream',
            'T': 'Task',
            't': 'UnsafeCurrentTask'
        }

        # If 1st character is 'c', we are looking @ a "Concurrency" type in the 'S' namespace
        # Read the following character to resolve concurrency type
        if char == 'c':
            next_c = self._next() # Consume the next char
            val = concurrency_types.get(next_c, f"UnknownConcurrency({next_c})")
            return val
        
        # Otherwise, look it up in the standard table
        return standard_types.get(char, f"UnknownType({char})")

    def _parse_sequence(self):
        # Main parsing loop
        while self.ptr < self.length:
            c = self._peek()
            
            # 1. Parsing Identifiers (Digits start identifiers)
            if c.isdigit():
                ident = self._parse_identifier()
                if ident: self.components.append(ident)
                continue

            # 2. Parsing Actions/Types (Letters)
            self._next() # Consume command char
            
            # --- Nominal Types ---
            if c == 'V': 
                self.detailed_info.append("Struct")
            elif c == 'C': 
                self.detailed_info.append("Class")
            elif c == 'O': 
                self.detailed_info.append("Enum")
            elif c == 'P': 
                self.detailed_info.append("Protocol")
            
            # --- Functions & Accessors ---
            elif c == 'F': 
                self.kind = "Function"
            elif c == 'g': 
                self.kind = "Getter"
            elif c == 's': 
                self.kind = "Setter"
            elif c == 'm': 
                self.kind = "MaterializeForSet"
            elif c == 'M': 
                self.kind = "Modify Accessor"
            elif c == 'I': 
                self.kind = "Initializer"
            elif c == 'D': 
                self.kind = "Deallocator"
            
            # --- Variable / Properties ---
            elif c == 'v':
                # 'v' usually precedes the accessor 'g' or 's'
                pass
            elif c == 'p':
                self.detailed_info.append("Property")
            
            # --- Standard Types (Recursion stop for this simplified parser) ---
            elif c == 'S':
                # Swift Standard Library Types
                next_c = self._next()
                type_name = self._parse_known_type(next_c)
                self.detailed_info.append(f"Return={type_name}")
            
            elif c == 't':
                # Tuple or ending
                pass
            
            # Ending conditions (simplification)
            if self.ptr >= self.length:
                break

# Regex to catch typical Swift symbols in assembly/pseudocode
# Catch _$s... and $s...
REGEX_SWIFT = re.compile(r'\b(_?\$s[a-zA-Z0-9_]+)\b')

def process(pseudocode_text):
    # Scan pseudo for Swift symbols, decode them, and add comments

    if not pseudocode_text: 
        return pseudocode_text

    lines = pseudocode_text.splitlines()
    final_lines = []
    
    # Cache to avoid re-parsing the same symbol 50 times
    cache = {}

    for line in lines:
        # Don't process lines that are already comments
        if line.strip().startswith("//"):
            final_lines.append(line)
            continue
            
        matches = REGEX_SWIFT.findall(line)
        comments = []
        
        for symbol in matches:
            if symbol in cache:
                decoded = cache[symbol]
            else:
                demangler = SwiftDemangler(symbol)
                decoded = demangler.demangle()
                cache[symbol] = decoded
            
            if decoded:
                comments.append(f"// Swift mangling - {decoded}")
        
        # Rebuild the line
        if comments:
            # Join multiple comments if multiple symbols exist on one line
            unique_comments = " ".join(sorted(list(set(comments))))
            final_lines.append(f"{line:<60}  {unique_comments}")
        else:
            final_lines.append(line)
            
    return "\n".join(final_lines)
    
def main():
    # Setup Arg Parser
    parser = argparse.ArgumentParser(
        description="Swift Symbol Demangler for Pseudocode/Assembly Files."
    )
    
    # -i (Input)
    parser.add_argument(
        "-i", "--input", 
        required=True, 
        help="Path to the input file (pseudocode or assembly text)."
    )
    
    # -o (Output)
    parser.add_argument(
        "-o", "--output", 
        required=True, 
        help="Path where the demangled version will be saved."
    )

    args = parser.parse_args()


    # Validate Input File
    if not os.path.exists(args.input):
        print(f"Error: The input file '{args.input}' was not found.")
        sys.exit(1)

    print(f"Processing: {args.input}...")


    # Read Input
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)


    # Process
    # Using the existing logic you wrote
    new_content = process(content)


    # Write Output
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Success! Demangled code written to: {args.output}")
    except Exception as e:
        print(f"Error writing output file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()