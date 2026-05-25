#  Swift Demangler

import re
import argparse
import os
import sys

class SwiftDemangler:
    def __init__(self, symbol):
        self.raw = symbol
        self.ptr = 0
        self.length = len(symbol)
        self.components = []
        self.kind = "Unknown"
        self.access = "default"
        self.detailed_info = []
        self.substitutions = []
        self._just_parsed_ident = False
        self._in_entity_path = True

    def demangle(self):
        if self.raw.startswith('_$s'):
            self.ptr = 3
        elif self.raw.startswith('$s'):
            self.ptr = 2
        else:
            return None

        try:
            self._parse_sequence()
            return self._format_result()
        except Exception:
            return None

    def _format_result(self):
        name_path = ".".join(self.components)
        details = f"demangled name = {name_path}"
        if self.kind:
            details += f", type = {self.kind}"
        if self.detailed_info:
            details += f" ({', '.join(self.detailed_info)})"
        return details

    def _peek(self):
        return self.raw[self.ptr] if self.ptr < self.length else None

    def _next(self):
        c = self._peek()
        if c: self.ptr += 1
        return c

    def _read_int(self):
        num_str = ""
        while self.ptr < self.length and self.raw[self.ptr].isdigit():
            num_str += self.raw[self.ptr]
            self.ptr += 1
        return int(num_str) if num_str else 0

    def _read_index(self):
        # INDEX ::= '_' (=0) | NATURAL '_' (=N+1)
        if self.ptr < self.length and self.raw[self.ptr] == '_':
            self.ptr += 1
            return 0
        n = self._read_int()
        if self.ptr < self.length and self.raw[self.ptr] == '_':
            self.ptr += 1
        return n + 1

    def _parse_identifier(self):
        if self.ptr >= self.length or not self.raw[self.ptr].isdigit():
            return None
        length = self._read_int()
        if self.ptr + length > self.length:
            return None
        ident = self.raw[self.ptr : self.ptr + length]
        self.ptr += length
        return ident

    # Substitution Stack
    def _push_substitution(self, name):
        if name:
            self.substitutions.append(name)

    def _decode_substitution_index(self):
        # Swift bijective base-36: S_ =0, S0_ =1, SA_ =11, S00_ =37
        saved_ptr = self.ptr
        index_str = ""
        while self.ptr < self.length:
            c = self.raw[self.ptr]
            if c == '_':
                self.ptr += 1
                break
            elif c.isdigit() or c.isupper():
                index_str += c
                self.ptr += 1
            else:
                self.ptr = saved_ptr
                return None
        if index_str == "":
            return 0
        n = 0
        for ch in index_str:
            n *= 36
            if ch.isdigit():
                n += int(ch) + 1
            else:
                n += ord(ch) - ord('A') + 11
        return n

    def _resolve_substitution(self):
        idx = self._decode_substitution_index()
        if idx is not None and idx < len(self.substitutions):
            return self.substitutions[idx]
        return None

    # Known Type Tables
    _STANDARD_ABBREVS = set('AabDdfhIiJNnOPpRrSsuVvWwqBEeFGHjKkLlMmQTtUXxYyZz')

    def _parse_known_type(self, char):
        standard_types = {
            'A': 'AutoreleasingUnsafeMutablePointer', 'a': 'Array',
            'b': 'Bool', 'D': 'Dictionary', 'd': 'Double', 'f': 'Float',
            'h': 'Set', 'I': 'DefaultIndices', 'i': 'Int', 'J': 'Character',
            'N': 'ClosedRange', 'n': 'Range', 'O': 'ObjectIdentifier',
            'P': 'UnsafePointer', 'p': 'UnsafeMutablePointer',
            'R': 'UnsafeBufferPointer', 'r': 'UnsafeMutableBufferPointer',
            'S': 'String', 's': 'Substring', 'u': 'UInt',
            'V': 'UnsafeRawPointer', 'v': 'UnsafeMutableRawPointer',
            'W': 'UnsafeRawBufferPointer', 'w': 'UnsafeMutableRawBufferPointer',
            'q': 'Optional', 'B': 'BinaryFloatingPoint', 'E': 'Encodable',
            'e': 'Decodable', 'F': 'FloatingPoint', 'G': 'RandomNumberGenerator',
            'H': 'Hashable', 'j': 'Numeric', 'K': 'BidirectionalCollection',
            'k': 'RandomAccessCollection', 'L': 'Comparable', 'l': 'Collection',
            'M': 'MutableCollection', 'm': 'RangeReplaceableCollection',
            'Q': 'Equatable', 'T': 'Sequence', 't': 'IteratorProtocol',
            'U': 'UnsignedInteger', 'X': 'RangeExpression', 'x': 'Strideable',
            'Y': 'RawRepresentable', 'y': 'StringProtocol',
            'Z': 'SignedInteger', 'z': 'BinaryInteger',
        }
        concurrency_types = {
            'A': 'Actor', 'C': 'CheckedContinuation', 'c': 'UnsafeContinuation',
            'E': 'CancellationError', 'e': 'UnownedSerialExecutor', 'F': 'Executor',
            'f': 'SerialExecutor', 'G': 'TaskGroup', 'g': 'ThrowingTaskGroup',
            'h': 'TaskExecutor', 'I': 'AsyncIteratorProtocol', 'i': 'AsyncSequence',
            'J': 'UnownedJob', 'M': 'MainActor', 'P': 'TaskPriority',
            'S': 'AsyncStream', 's': 'AsyncThrowingStream', 'T': 'Task',
            't': 'UnsafeCurrentTask',
        }
        if char == 'c':
            nc = self._next()
            return concurrency_types.get(nc, f"UnknownConcurrency({nc})")
        return standard_types.get(char, f"UnknownType({char})")

    # Generic param index parser
    def _parse_generic_param_index(self):
        # GENERIC-PARAM-INDEX ::= 'z' (depth=0,idx=0) | INDEX (depth=0,idx=N+1)
        #                       | 'd' INDEX INDEX (depth=M+1,idx=N)
        if self.ptr >= self.length:
            return "param(?)"
        c = self.raw[self.ptr]
        if c == 'z':
            self.ptr += 1
            return "T_0_0"
        elif c == 'd':
            self.ptr += 1
            depth = self._read_index()
            idx = self._read_index()
            return f"T_{depth+1}_{idx}"
        else:
            idx = self._read_index()
            return f"T_0_{idx}"

    # Main parsing loop
    def _parse_sequence(self):
        while self.ptr < self.length:
            c = self._peek()

            # Digits → identifier
            if c.isdigit():
                ident = self._parse_identifier()
                if ident:
                    self.components.append(ident)
                    self._push_substitution(".".join(self.components))
                    self._just_parsed_ident = True
                continue

            self._next()

            # Known module abbreviations (appear right after prefix as first token)
            # known-module ::= 's' (Swift) | 'SC' (Clang-synthesized) | 'So' (ObjC/C)
            if c == 's' and self._in_entity_path and not self.components:
                # 's' as very first token = Swift standard library module
                nc = self._peek()
                if nc == 'C':
                    self._next()
                    self.components.append("__C_Synthesized")
                    self._push_substitution("__C_Synthesized")
                elif nc == 'o':
                    self._next()
                    self.components.append("__C")
                    self._push_substitution("__C")
                else:
                    self.components.append("Swift")
                    self._push_substitution("Swift")
                self._just_parsed_ident = True
                continue
            elif c == 's' and not (self._in_entity_path and not self.components):
                self.kind = "Setter"
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'A' — substitution back-reference, private discriminator, or generic param
            # Spec: substitution ::= 'A' INDEX (=N+26) | 'A' SUBST-IDX* LAST-SUBST-IDX
            if c == 'A':
                if self._in_entity_path and self.ptr < self.length and self.raw[self.ptr].isdigit():
                    # Private discriminator between two identifier segments — merge
                    self.detailed_info.append("PrivateDiscriminator")
                    next_ident = self._parse_identifier()
                    if next_ident and self.components:
                        self.components[-1] += next_ident
                        self._push_substitution(".".join(self.components))
                    self._just_parsed_ident = True
                elif self._in_entity_path:
                    # Substitution back-reference chain in entity path context
                    # spec: 'A' SUBST-IDX* LAST-SUBST-IDX
                    nc = self._peek()
                    if nc is not None and (nc.islower() or nc.isupper()):
                        letters = ""
                        while self.ptr < self.length:
                            ch = self.raw[self.ptr]
                            if ch.islower():
                                letters += ch; self.ptr += 1
                            elif ch.isupper():
                                letters += ch; self.ptr += 1; break
                            elif ch.isdigit():
                                count = self._read_int()
                                if self.ptr < self.length:
                                    rep_ch = self.raw[self.ptr]; self.ptr += 1
                                    letters += rep_ch * count
                                break
                            else:
                                break
                        for letter in letters:
                            idx = ord(letter) - ord('a') if letter.islower() else ord(letter) - ord('A')
                            if idx < len(self.substitutions):
                                resolved = self.substitutions[idx]
                                self.components.append(resolved)
                                self.detailed_info.append(f"Subst={resolved}")
                    else:
                        idx = self._read_index() + 26
                        if idx < len(self.substitutions):
                            resolved = self.substitutions[idx]
                            self.components.append(resolved)
                            self.detailed_info.append(f"Subst={resolved}")
                        else:
                            self.detailed_info.append("GenericParam(A)")
                    self._in_entity_path = False
                    self._just_parsed_ident = False
                else:
                    # In type-encoding position: 'A' = generic type parameter ref
                    self.detailed_info.append("GenericParam(A)")
                    self._just_parsed_ident = False

            # --- Nominal Types ---
            elif c == 'V':
                self.detailed_info.append("Struct")
                if self.components:
                    self._push_substitution(".".join(self.components))
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'C':
                if self._just_parsed_ident:
                    self.detailed_info.append("Class")
                    if self.components:
                        self._push_substitution(".".join(self.components))
                else:
                    self.detailed_info.append("AllocatingConstructor")
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'O':
                self.detailed_info.append("Enum")
                if self.components:
                    self._push_substitution(".".join(self.components))
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'P':
                self.detailed_info.append("Protocol")
                if self.components:
                    self._push_substitution(".".join(self.components))
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'x' — generic type parameter, depth=0, idx=0 (the single-param shorthand)
            # spec: type ::= 'x'  // generic param, depth=0, idx=0
            elif c == 'x':
                self.detailed_info.append("GenericParam(T_0_0)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'q' — generic parameter with explicit index
            # spec: type ::= 'q' GENERIC-PARAM-INDEX
            elif c == 'q':
                param = self._parse_generic_param_index()
                self.detailed_info.append(f"GenericParam({param})")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # --- Functions & Accessors ---
            elif c == 'F':
                self.kind = "Function"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'g':
                self.kind = "Getter"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'G':
                self.kind = "GlobalGetter"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'M':
                nc = self._peek()
                meta_map = {
                    'f': 'FullTypeMetadata', 'P': 'TypeMetadataPattern',
                    'a': 'TypeMetadataAccessFunction', 'L': 'TypeMetadataLazyCache',
                    'r': 'GenericTypeCompletionFunction', 'i': 'GenericTypeInstantiationFunction',
                    'I': 'GenericTypeInstantiationCache', 'l': 'InPlaceTypeInitCache',
                    'm': 'ClassMetaclass', 'n': 'NominalTypeDescriptor',
                    'o': 'ClassMetadataImmediateMemberBaseOffset',
                    'u': 'ClassMethodLookupFunction', 'U': 'ObjCMetadataUpdateCallback',
                    's': 'ObjCResilientClassStub', 't': 'FullObjCResilientClassStub',
                    'F': 'FieldDescriptor', 'B': 'BuiltinTypeDescriptor',
                    'A': 'AssociatedTypeDescriptor', 'C': 'SuperclassDescriptor',
                    'S': 'ProtocolSelfConformanceDescriptor', 'Q': 'OpaqueTypeDescriptor',
                    'J': 'NoncanonicalSpecializedGenericMetadataCache',
                    'N': 'NoncanonicalSpecializedGenericMetadata',
                    'z': 'CanonicalSpecializedGenericMetadataCachingToken',
                    'q': 'GlobalWithUniquingPrefix', 'K': 'InstantiationCache',
                    'p': 'ProtocolDescriptor',
                }
                if nc == 'X':
                    self.ptr += 1
                    nc2 = self._peek()
                    mx_map = {
                        'M': 'ModuleDescriptor', 'E': 'ExtensionDescriptor',
                        'X': 'AnonymousContextDescriptor', 'Y': 'AnonymousContextDescriptorWithName',
                        'A': 'GenericParameterRef',
                    }
                    if nc2 in mx_map:
                        self._next()
                        self.detailed_info.append(f"MX{nc2}={mx_map[nc2]}")
                    else:
                        self.detailed_info.append(f"MX{nc2 or '?'}")
                    self.kind = "ModuleDescriptor"
                elif nc in meta_map:
                    self._next()
                    self.detailed_info.append(f"M{nc}={meta_map[nc]}")
                    self.kind = meta_map[nc]
                elif self._just_parsed_ident:
                    self.kind = "MaterializeForSet"
                else:
                    self.kind = "Modify Accessor"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'I':
                self.kind = "Initializer"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'D':
                self.kind = "Deallocator"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'd':
                self.kind = "Destructor"
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'e':
                self.kind = "ivar Initializer"
                self._in_entity_path = False
                self._just_parsed_ident = False

            # Entity-spec 'f' family — constructors, closures, accessors
            # entity-spec ::= label-list type 'fC' | 'fc' | 'fD' | 'fd' | 'fU' | 'fu' | etc.
            elif c == 'f':
                nc = self._peek()
                if nc == 'C':
                    self._next()
                    self.kind = "AllocatingConstructor"
                    self.detailed_info.append("fC=allocating init")
                elif nc == 'c':
                    self._next()
                    self.kind = "NonAllocatingConstructor"
                    self.detailed_info.append("fc=init body")
                elif nc == 'D':
                    self._next()
                    self.kind = "DeallocatingDestructor"
                    self.detailed_info.append("fD=deallocating deinit")
                elif nc == 'd':
                    self._next()
                    self.kind = "NonDeallocatingDestructor"
                    self.detailed_info.append("fd=deinit body")
                elif nc == 'E':
                    self._next()
                    self.detailed_info.append("fE=ivar destroyer")
                elif nc == 'e':
                    self._next()
                    self.detailed_info.append("fe=ivar initializer")
                elif nc == 'i':
                    self._next()
                    self.detailed_info.append("fi=non-local variable initializer")
                elif nc == 'P':
                    self._next()
                    self.detailed_info.append("fP=property wrapper backing initializer")
                elif nc == 'U':
                    self._next()
                    self.detailed_info.append("fU=explicit anonymous closure")
                elif nc == 'u':
                    self._next()
                    self.detailed_info.append("fu=implicit anonymous closure")
                elif nc == 'A':
                    self._next()
                    self.detailed_info.append("fA=default argument generator")
                elif nc == 'Z':
                    self._next()
                    self.detailed_info.append("fZ=isolated deallocating destructor")
                elif nc == 'F':
                    self._next()
                    self.detailed_info.append("fF=property wrapped field init accessor")
                elif nc == 'W':
                    self._next()
                    self.detailed_info.append("fW=property wrapper init from projected value")
                elif nc == 'M':
                    # 'fM' = macro expansion family
                    self._next()
                    mc = self._peek()
                    if mc in ('a','r','f','m','p','c','e','q','b','u'):
                        self._next()
                        macro_kinds = {
                            'a': 'attached accessor macro', 'r': 'attached member-attribute macro',
                            'f': 'freestanding macro', 'm': 'attached member macro',
                            'p': 'attached peer macro', 'c': 'attached conformance macro',
                            'e': 'attached extension macro', 'q': 'attached preamble macro',
                            'b': 'attached body macro', 'u': 'uniquely-named entity',
                        }
                        self.detailed_info.append(f"fM{mc}={macro_kinds.get(mc,'macro')}")
                    else:
                        self.detailed_info.append("fM=macro expansion")
                else:
                    self.detailed_info.append("PartialApplyForwarder")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'v' — variable/property entity-spec
            elif c == 'v':
                self._just_parsed_ident = False

            elif c == 'p':
                self.detailed_info.append("Property")
                self._just_parsed_ident = False

            # Function signature type markers
            elif c == 'c':
                self.detailed_info.append("FuncType")
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'y':
                self.detailed_info.append("Void")
                self._in_entity_path = False
                self._just_parsed_ident = False

            elif c == 'm':
                if self._just_parsed_ident:
                    self.kind = "MaterializeForSet"
                else:
                    self.detailed_info.append("Metatype(.Type)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'K' — throws annotation on function types
            elif c == 'K':
                self.detailed_info.append("throws")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'u' — generic type (type + generic-signature 'u')
            elif c == 'u':
                self.detailed_info.append("GenericType")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'Z' — static member marker (also used in WZ global init)
            elif c == 'Z':
                self.detailed_info.append("StaticMember")
                self._just_parsed_ident = False

            # 'N' — type metadata (global ::= type 'N') or ClosedRange (S+N)
            # In entity position after a type = type metadata address point
            elif c == 'N':
                self.detailed_info.append("TypeMetadata")
                self.kind = "TypeMetadata"
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'n' — nominal type descriptor (global ::= nominal-type 'Mn' via M+n)
            # Standalone 'n' in entity position = Range (handled via Sn)



            # 'B' family — Builtin types (Bb, BI, Bo, Bp, Bt, Bw, etc.)
            elif c == 'B':
                nc = self._peek()
                builtin_map = {
                    'b': 'Builtin.BridgeObject', 'B': 'Builtin.UnsafeValueBuffer',
                    'c': 'Builtin.RawUnsafeContinuation', 'D': 'Builtin.DefaultActorStorage',
                    'e': 'Builtin.Executor', 'd': 'Builtin.NonDefaultDistributedActorStorage',
                    'I': 'Builtin.IntLiteral', 'j': 'Builtin.Job', 'O': 'Builtin.UnknownObject',
                    'o': 'Builtin.NativeObject', 'p': 'Builtin.RawPointer',
                    't': 'Builtin.SILToken', 'w': 'Builtin.Word', 'P': 'Builtin.PackIndex',
                    'A': 'Builtin.ImplicitActor',
                }
                if nc == 'f':
                    self._next()
                    n = self._read_int()
                    if self.ptr < self.length and self.raw[self.ptr] == '_':
                        self.ptr += 1
                    self.detailed_info.append(f"Builtin.Float{n}")
                elif nc == 'i':
                    self._next()
                    n = self._read_int()
                    if self.ptr < self.length and self.raw[self.ptr] == '_':
                        self.ptr += 1
                    self.detailed_info.append(f"Builtin.Int{n}")
                elif nc in builtin_map:
                    self._next()
                    self.detailed_info.append(builtin_map[nc])
                else:
                    self.detailed_info.append(f"Builtin(?)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'H' — runtime records (Hr, Hn, Ho, Hc, HF) and Hashable (SH)
            elif c == 'H':
                nc = self._peek()
                h_map = {
                    'r': 'ProtocolDescriptorRuntimeRecord',
                    'n': 'NominalTypeDescriptorRuntimeRecord',
                    'o': 'OpaqueTypeDescriptorRuntimeRecord',
                    'c': 'ProtocolConformanceRuntimeRecord',
                    'F': 'AccessibleFunctionRuntimeRecord',
                    'C': 'ConcreteProtocolConformance',
                    'P': 'ProtocolConformanceRef(sameModule)',
                    'p': 'ProtocolConformanceRef(protoModule)',
                    'D': 'DependentProtocolConformance',
                    'I': 'InheritedConformanceLookup',
                    'A': 'AssociatedConformanceLookup',
                    'O': 'DependentConformanceLookup',
                    'X': 'PackProtocolConformance',
                }
                if nc in h_map:
                    self._next()
                    self.detailed_info.append(h_map[nc])
                else:
                    self.detailed_info.append(f"H{nc or '?'}")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'R' — generic requirements (conformance, same-type, base class, etc.)
            # requirement ::= protocol 'R' GENERIC-PARAM-INDEX  (conformance)
            elif c == 'R':
                nc = self._peek()
                if nc == 'z':
                    # 'Rz' = generic signature has one param (depth=0,idx=0)
                    # This appears at end of generic sig before 'l'
                    self.detailed_info.append("Req:ConformsTo(T_0_0)")
                    self._next()
                elif nc == 'l':
                    self.detailed_info.append("Req:Layout")
                    self._next()
                elif nc == 'b':
                    self.detailed_info.append("Req:BaseClass")
                    self._next()
                elif nc == 's':
                    self.detailed_info.append("Req:SameType")
                    self._next()
                elif nc == 'c':
                    self.detailed_info.append("Req:BaseClassOnAssocType")
                    self._next()
                elif nc == 'p':
                    self.detailed_info.append("Req:ProtoOnAssocType")
                    self._next()
                elif nc == 'P':
                    self.detailed_info.append("Req:ProtoOnAssocTypeAtDepth")
                    self._next()
                elif nc == 't':
                    self.detailed_info.append("Req:SameTypeOnAssocType")
                    self._next()
                elif nc == 'h':
                    self.detailed_info.append("Req:SameShape")
                    self._next()
                elif nc == 'i':
                    self.detailed_info.append("Req:InverseOnParam")
                    self._next()
                elif nc == 'j':
                    self.detailed_info.append("Req:InverseOnAssocType")
                    self._next()
                elif nc == 'v':
                    self.detailed_info.append("GenericParamPackMarker")
                    self._next()
                else:
                    # protocol 'R' GENERIC-PARAM-INDEX = conformance requirement
                    param = self._parse_generic_param_index()
                    self.detailed_info.append(f"Req:ConformsTo({param})")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'l' — generic signature terminator (single generic param marker)
            # generic-signature ::= requirement* generic-param-marker 'l'
            elif c == 'l':
                self.detailed_info.append("GenericSig")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'r' — generic type completion / reabstraction / generic sig context
            # In generic signature: 'r' GENERIC-PARAM-COUNT* 'l' (multi-depth sig)
            elif c == 'r':
                self.detailed_info.append("GenericSig(multi)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # '_' — parameter label separator, empty label, INDEX terminator
            elif c == '_':
                self.detailed_info.append("Separator")
                self._just_parsed_ident = False

            # 'T' family — thunks and other global wrappers
            elif c == 'T':
                nc = self._peek()
                t_map = {
                    'A': 'PartialApplicationForwarder', 'a': 'ObjCPartialAppForwarder',
                    'Q': 'AsyncAwaitContinuationPartialFunc', 'Y': 'AsyncSuspendContinuationPartialFunc',
                    'O': 'ObjCAsSwiftThunk', 'o': 'SwiftAsObjCThunk',
                    'D': 'DynamicDispatchThunk', 'd': 'DirectMethodReferenceThunk',
                    'E': 'DistributedActorThunk', 'F': 'DistributedMethodAccessor',
                    'I': 'DynamicReplaceableImpl', 'u': 'AsyncFunctionPointer',
                    'X': 'DynamicReplaceableFunctionPointer',
                    'W': 'ProtocolWitnessThunk', 'S': 'ProtocolSelfConformanceWitnessThunk',
                    'j': 'ResilientMethodDispatchThunk', 'q': 'MethodDescriptor',
                    'V': 'VTableOverrideThunk', 'K': 'KeyPathGetter',
                    'k': 'KeyPathSetter', 'H': 'KeyPathEquality', 'h': 'KeyPathHasher',
                    'L': 'ProtocolRequirementsBaseDescriptor',
                    'l': 'AssociatedTypeDescriptor', 'M': 'DefaultAssocTypeWitnessAccessor',
                    'n': 'AssociatedConformanceDescriptor', 'N': 'DefaultAssocConformanceAccessor',
                    'b': 'BaseConformanceDescriptor', 'R': 'ReabstractionThunk',
                    'r': 'ObsoleteReabstractionThunk', 'y': 'ReabstractionThunkWithSelf',
                    'U': 'ReabstractionThunkWithGlobalActor',
                    'c': 'CurryThunk', 'm': 'MergedFunction',
                }
                if nc == 'w':
                    self._next()
                    nc2 = self._peek()
                    tw_map = {
                        'b': 'BackDeploymentThunk', 'B': 'BackDeploymentFallback',
                        'c': 'CoroutineFunctionPointer', 'd': 'DefaultOverride',
                        'S': 'HasSymbolQueryFunction',
                    }
                    if nc2 in tw_map:
                        self._next()
                        self.detailed_info.append(tw_map[nc2])
                    else:
                        self.detailed_info.append(f"Tw{nc2 or '?'}")
                elif nc == 'J':
                    self._next()
                    self.detailed_info.append("AutoDiffFunction")
                elif nc in t_map:
                    self._next()
                    self.detailed_info.append(t_map[nc])
                    self.kind = t_map[nc]
                else:
                    self.detailed_info.append(f"Thunk(T{nc or '?'})")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'W' family — witness tables and value witnesses
            elif c == 'W':
                nc = self._peek()
                if nc == 'O':
                    self._next()
                    nc2 = self._peek()
                    wo_map = {
                        'y': 'OutlinedCopy', 'e': 'OutlinedConsume',
                        'r': 'OutlinedRetain', 's': 'OutlinedRelease',
                        'B': 'OutlinedInitWithTake(noWitness)', 'b': 'OutlinedInitWithTake',
                        'c': 'OutlinedInitWithCopy', 'C': 'OutlinedInitWithCopy(noWitness)',
                        'd': 'OutlinedAssignWithTake', 'D': 'OutlinedAssignWithTake(noWitness)',
                        'f': 'OutlinedAssignWithCopy', 'F': 'OutlinedAssignWithCopy(noWitness)',
                        'h': 'OutlinedDestroy', 'H': 'OutlinedDestroy(noWitness)',
                        'i': 'OutlinedStoreEnumTag', 'j': 'OutlinedEnumDestructiveProject',
                        'g': 'OutlinedEnumGetTag',
                    }
                    if nc2 in wo_map:
                        self._next()
                        self.detailed_info.append(f"WO{nc2}={wo_map[nc2]}")
                    else:
                        self.detailed_info.append(f"WO{nc2 or '?'}")
                elif nc == 'V':
                    self._next()
                    self.detailed_info.append("ValueWitnessTable")
                    self.kind = "ValueWitnessTable"
                elif nc == 'J':
                    self._next()
                    self.detailed_info.append("DifferentiabilityWitness")
                elif nc == 'Z':
                    self._next()
                    self.detailed_info.append("GlobalVarOneTimeInitFunc")
                elif nc == 'z':
                    self._next()
                    self.detailed_info.append("GlobalVarOneTimeInitToken")
                elif nc == 'S':
                    self._next()
                    self.detailed_info.append("ProtocolSelfConformanceWitnessTable")
                else:
                    witness_kinds = {
                        'C': 'WitnessTableConformance', 'P': 'ProtocolWitnessTable',
                        'G': 'GenericWitnessTable', 'I': 'WitnessTableAccessor',
                        'a': 'ProtocolWitnessTableAccessor', 'l': 'LazyWitnessTableCache',
                        'D': 'AssociatedTypeDescriptor', 'o': 'WitnessOffset',
                        'p': 'ProtocolWitnessTablePattern',
                        'r': 'ResilientWitnessTable', 'L': 'LazyWitnessTableCacheVariable',
                        't': 'AssocTypeMetadataAccessor', 'T': 'AssocTypeWitnessTableAccessor',
                        'b': 'BaseProtocolWitnessTableAccessor',
                    }
                    if nc in witness_kinds:
                        self._next()
                        self.detailed_info.append(witness_kinds[nc])
                    else:
                        self.detailed_info.append(f"Witness(W{nc or '?'})")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'X' family — special types and extended existentials
            elif c == 'X':
                nc = self._peek()
                if nc == 'M':
                    self._next()
                    repr_c = self._peek()
                    if repr_c in ('t', 'T', 'o'):
                        self._next()
                        repr_map = {'t': 'thin', 'T': 'thick', 'o': 'ObjC'}
                        self.detailed_info.append(f"MetatypeWithRepr({repr_map[repr_c]})")
                    else:
                        self.detailed_info.append("ExistentialMetatype")
                elif nc == 'm':
                    self._next()
                    self.detailed_info.append("ExistentialMetatypeWithRepr")
                elif nc == 'o':
                    self._next()
                    self.detailed_info.append("@unowned")
                elif nc == 'u':
                    self._next()
                    self.detailed_info.append("@unowned(unsafe)")
                elif nc == 'w':
                    self._next()
                    self.detailed_info.append("@weak")
                elif nc == 'F':
                    self._next()
                    self.detailed_info.append("ImplFunctionType")
                elif nc == 'b':
                    self._next()
                    self.detailed_info.append("SILBoxType")
                elif nc == 'x':
                    self._next()
                    self.detailed_info.append("SILBoxTypeWithLayout")
                elif nc == 'X':
                    self._next()
                    self.detailed_info.append("GenericSILBoxType")
                elif nc == 'D':
                    self._next()
                    self.detailed_info.append("DynamicSelfType")
                elif nc == 'p':
                    self._next()
                    self.detailed_info.append("ExistentialMetatypeNoRepr")
                elif nc == 'c':
                    self._next()
                    self.detailed_info.append("ExistentialWithSuperclass")
                elif nc == 'l':
                    self._next()
                    self.detailed_info.append("ExistentialWithAnyObject")
                elif nc == 'P':
                    self._next()
                    self.detailed_info.append("ConstrainedExistentialType")
                elif nc == 'j':
                    self._next()
                    self.detailed_info.append("ExtendedExistentialType")
                elif nc == 'g':
                    self._next()
                    self.detailed_info.append("ExtendedExistentialShape(noSig)")
                elif nc == 'G':
                    self._next()
                    self.detailed_info.append("ExtendedExistentialShape(withSig)")
                elif nc == 'Y':
                    self._next()
                    self.detailed_info.append("UnknownNominalType")
                elif nc == 'Z':
                    self._next()
                    self.detailed_info.append("UnknownRuntimeContext")
                elif nc == 'S':
                    self._next()
                    xsuf = self._peek()
                    xs_map = {'q': 'SugaredOptional', 'a': 'SugaredArray', 'D': 'SugaredDictionary', 'A': 'SugaredInlineArray'}
                    if xsuf in xs_map:
                        self._next()
                        self.detailed_info.append(xs_map[xsuf])
                    else:
                        self.detailed_info.append("SugaredType")
                elif nc is not None and nc in 'fUKBLCAE':
                    self._next()
                    func_map = {
                        'f': '@thin function', 'U': 'uncurried function',
                        'K': '@auto_closure(noescape)', 'B': 'ObjC block',
                        'L': 'ObjC block(DWARF)', 'C': 'C function pointer',
                        'A': '@auto_closure(escaping)', 'E': 'noescape function',
                    }
                    self.detailed_info.append(f"SpecialFunc({func_map.get(nc, nc)})")
                else:
                    self.detailed_info.append(f"SpecialType(X{nc or '?'})")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'S' — stdlib abbreviations and back-references
            elif c == 'S':
                nc = self._peek()
                if nc == 'o':
                    # 'So' = ObjC/C module (__C)
                    self._next()
                    self.components.append("__C")
                    self._push_substitution("__C")
                    self._just_parsed_ident = True
                    continue
                elif nc == 'C':
                    # 'SC' = Clang-importer-synthesized module
                    self._next()
                    self.components.append("__C_Synthesized")
                    self._push_substitution("__C_Synthesized")
                    self._just_parsed_ident = True
                    continue
                elif nc == 'c':
                    self._next()
                    type_name = self._parse_known_type('c')
                    self.detailed_info.append(f"Type={type_name}")
                    self._push_substitution(type_name)
                elif nc == 'g':
                    self._next()
                    self.detailed_info.append("Type=Optional")
                    self._push_substitution("Optional")
                elif nc in self._STANDARD_ABBREVS:
                    self._next()
                    type_name = self._parse_known_type(nc)
                    self.detailed_info.append(f"Type={type_name}")
                    self._push_substitution(type_name)
                else:
                    resolved = self._resolve_substitution()
                    if resolved:
                        self.components.append(resolved)
                        self.detailed_info.append(f"Subst={resolved}")
                    else:
                        self.detailed_info.append("Subst=?")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'Q' family — opaque result types, associated types
            elif c == 'Q':
                nc = self._peek()
                q_map = {
                    'r': 'OpaqueResultType(first)', 'R': 'OpaqueResultType(index)',
                    'o': 'OpaqueType', 'O': 'OpaqueResultTypeOfDecl',
                    'u': 'OpaqueResultType(ObjC,first)', 'U': 'OpaqueResultType(ObjC,index)',
                    'y': 'AssociatedType', 'z': 'AssocType(shortcut)',
                    'Y': 'AssocTypeAtDepth', 'Z': 'AssocTypeAtDepthShortcut',
                    'a': 'AssociatedTypeOf', 'x': 'AssocTypeRelative',
                    'X': 'AssocTypeListRelative', 'e': 'PackElement',
                    'p': 'PackExpansion', 'P': 'PackType', 'S': 'SILPackType',
                }
                if nc in q_map:
                    self._next()
                    self.detailed_info.append(q_map[nc])
                else:
                    self.detailed_info.append(f"Q{nc or '?'}")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'Y' family — Swift 5.5+ function type annotations
            elif c == 'Y':
                nc = self._peek()
                y_map = {
                    'a': 'async', 'b': '@Sendable', 'c': 'GlobalActorIsolation',
                    'A': '@isolated(any)', 'T': 'sending result',
                    'K': 'throws(typed)', 'C': 'nonisolated(nonsending)',
                    'i': 'IsolatedParameter',
                }
                if nc in y_map:
                    self._next()
                    self.detailed_info.append(y_map[nc])
                else:
                    self.detailed_info.append(f"Y{nc or '?'}")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'w' — value witnesses (global ::= type 'w' VALUE-WITNESS-KIND)
            elif c == 'w':
                nc = self._peek()
                vw_map = {
                    'al': 'AllocateBuffer', 'ca': 'AssignWithCopy', 'ta': 'AssignWithTake',
                    'de': 'DeallocateBuffer', 'xx': 'Destroy', 'XX': 'DestroyBuffer',
                    'Xx': 'DestroyArray', 'CP': 'InitBufferWithCopyOfBuffer',
                    'Cp': 'InitBufferWithCopy', 'cp': 'InitWithCopy',
                    'TK': 'InitBufferWithTakeOfBuffer', 'Tk': 'InitBufferWithTake',
                    'tk': 'InitWithTake', 'pr': 'ProjectBuffer',
                    'xs': 'StoreExtraInhabitant', 'xg': 'GetExtraInhabitantIndex',
                    'Cc': 'InitArrayWithCopy', 'Tt': 'InitArrayWithTakeFrontToBack',
                    'tT': 'InitArrayWithTakeBackToFront', 'ug': 'GetEnumTag',
                    'up': 'DestructiveProjectEnumData', 'ui': 'DestructiveInjectEnumTag',
                    'et': 'GetEnumTagSinglePayload', 'st': 'StoreEnumTagSinglePayload',
                }
                # Read two chars for value witness kind
                if nc is not None and self.ptr + 1 < self.length:
                    two = self.raw[self.ptr:self.ptr+2]
                    if two in vw_map:
                        self.ptr += 2
                        self.detailed_info.append(f"ValueWitness({vw_map[two]})")
                    else:
                        self.detailed_info.append(f"ValueWitness(w{nc or '?'})")
                else:
                    self.detailed_info.append(f"ValueWitness(?)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 't' — tuple type or parameter list end
            elif c == 't':
                self.detailed_info.append("Tuple/ParamEnd")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'L' — locally/file discriminated declaration
            # decl-name ::= identifier 'L' INDEX
            elif c == 'L':
                nc = self._peek()
                if nc == 'l':
                    self._next()
                    self.detailed_info.append("FileDiscriminator")
                elif nc == 'L':
                    self._next()
                    self.detailed_info.append("FileDiscriminatedDecl")
                else:
                    idx = self._read_index()
                    self.detailed_info.append(f"LocalDiscriminator({idx})")
                self._just_parsed_ident = False

            # 'E' — extension context
            elif c == 'E':
                self.detailed_info.append("Extension")
                self._just_parsed_ident = False

            # 'z' — in GENERIC-PARAM-INDEX position = first param; otherwise BinaryInteger
            # In context after parsing it may appear standalone as first generic param
            elif c == 'z':
                self.detailed_info.append("GenericParam(T_0_0)")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # 'n' — standalone = Range type (via Sn). As entity spec: nominal type descriptor
            # In practice standalone 'n' here means NominalTypeDescriptor suffix was split
            elif c == 'n':
                self.detailed_info.append("NominalTypeDescriptor")
                self._in_entity_path = False
                self._just_parsed_ident = False

            # Unknown — record so nothing silently disappears
            else:
                self.detailed_info.append(f"Unknown({c})")
                self._just_parsed_ident = False

            if self.ptr >= self.length:
                break


# Regex to catch typical Swift symbols in assembly/pseudocode
# Catch _$s... and $s...
REGEX_SWIFT = re.compile(r'\b(_?\$s[a-zA-Z0-9_$]+)\b')

def process(pseudocode_text):
    if not pseudocode_text:
        return pseudocode_text

    lines = pseudocode_text.splitlines()
    final_lines = []
    cache = {}

    for line in lines:
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

        if comments:
            unique_comments = " ".join(sorted(list(set(comments))))
            final_lines.append(f"{line:<60}  {unique_comments}")
        else:
            final_lines.append(line)

    return "\n".join(final_lines)

def main():
    parser = argparse.ArgumentParser(
        description="Swift Symbol Demangler for Pseudocode/Assembly Files."
    )
    parser.add_argument("-i", "--input", required=True,
        help="Path to the input file (pseudocode or assembly text).")
    parser.add_argument("-o", "--output", required=True,
        help="Path where the demangled version will be saved.")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: The input file '{args.input}' was not found.")
        sys.exit(1)

    print(f"Processing: {args.input}...")

    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading input file: {e}")
        sys.exit(1)

    new_content = process(content)

    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Success! Demangled code written to: {args.output}")
    except Exception as e:
        print(f"Error writing output file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
